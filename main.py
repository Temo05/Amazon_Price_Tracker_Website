from flask import Flask, render_template, redirect, flash, url_for, abort, request, jsonify
from dotenv import load_dotenv, find_dotenv
from flask_wtf import FlaskForm
from wtforms import StringField, EmailField, PasswordField, SubmitField, FloatField
from wtforms.validators import DataRequired, Email, length, EqualTo, Length, URL
from flask_bootstrap import Bootstrap
from sqlalchemy import Integer, String, ForeignKey, Float, Boolean
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import  DeclarativeBase, Mapped, mapped_column, relationship
from flask_login import UserMixin, login_user, logout_user, current_user, login_required, LoginManager
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy.exc import IntegrityError
from functools import wraps
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from tracker import update_products
import time, os, pytz

path = find_dotenv()
load_dotenv(path)

class Base(DeclarativeBase):
    pass

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get("DB_URL", "sqlite:///tracker.db")
app.config['SECRET_KEY'] = os.getenv("SECRET_KEY")
db = SQLAlchemy(model_class=Base)
db.init_app(app)
bootstrap = Bootstrap(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "/login"

chrome_options = webdriver.ChromeOptions()
chrome_options.add_argument("--headless")
chrome_options.add_argument("--no-sandbox")
chrome_options.add_argument("--disable-dev-shm-usage")
chrome_options.add_argument("--disable-gpu")
chrome_options.add_argument("--disable-extensions")
chrome_options.binary_location = "/run/current-system/sw/bin/chromium"
chrome_options.page_load_strategy = 'eager'


def admin_only(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if current_user.id == 1:
            return f(*args, **kwargs)
        else:
            abort(403)
    return decorated_function


def seeProduct(url):
    driver = webdriver.Chrome(options=chrome_options)
    driver.get(url)

    try:
        WebDriverWait(driver, 3).until(
            EC.element_to_be_clickable((By.XPATH, "/html/body/div/div[1]/div[3]/div/div/form/div/div/span/span/button"))
        ).click()
    except:
        pass

    name = WebDriverWait(driver, 5).until(
        EC.presence_of_element_located((By.ID, "productTitle"))
    ).text.split(",")[0].strip()

    price = None
    selectors = [
        (By.CLASS_NAME, "a-offscreen"),
        (By.CLASS_NAME, "a-price-whole"),
        (By.ID, "priceblock_ourprice"),
        (By.ID, "priceblock_dealprice"),
    ]

    for by, selector in selectors:
        try:
            price = WebDriverWait(driver, 3).until(
                EC.presence_of_element_located((by, selector))
            ).text.replace(",", "").replace("GEL", "").replace("$", "").strip()
            if price:
                break
        except:
            continue

    driver.quit()

    if not price:
        raise Exception("Price not found")

    return name, float(price)

class User(UserMixin, db.Model):
    __tablename__ = 'users'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String, unique=True)
    password: Mapped[str] = mapped_column(String, nullable=False)
    products = relationship("Products", back_populates="user")


class Products(db.Model):
    __tablename__ = 'products'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    amazon_url: Mapped[str] = mapped_column(String, nullable=False)
    desired_price: Mapped[float] = mapped_column(Float, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    current_price: Mapped[float] = mapped_column(Float, nullable=False)
    price_bellow: Mapped[bool] = mapped_column(Boolean, nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"))
    user = relationship("User", back_populates="products")

    def to_dict(self):
        dictionary = {}
        for col in self.__table__.columns:
            dictionary[col.name] = getattr(self, col.name)
        return dictionary

class RegisterForm(FlaskForm):
    email = EmailField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired(), length(min=8, max=32)])
    password2 = PasswordField('Repeat Password', validators=[DataRequired(), EqualTo('password')])
    submit = SubmitField('Register')

class LoginForm(FlaskForm):
    email = EmailField('Email', validators=[DataRequired()])
    password = PasswordField('Password', validators=[DataRequired()])
    submit = SubmitField('Login')

class ProductForm(FlaskForm):
    amazon_url = StringField("Amazon Product URL", validators=[DataRequired(), URL()])
    desired_price = FloatField("Target Price (GEL)", validators=[DataRequired()])
    submit = SubmitField('Submit')

class editForm(FlaskForm):
    desired_price = FloatField("Target Price (GEL)", validators=[DataRequired()])
    submit = SubmitField('Submit')

try:
    with app.app_context():
        db.create_all()
except Exception as e:
    pass

scheduler = BackgroundScheduler()
scheduler.add_job(
    func=lambda: update_products(app, db, Products, seeProduct),
    trigger=CronTrigger(hour=5, minute=0, timezone=pytz.utc)  # UTC 5:00 = GMT+4 9:00
)
scheduler.start()


def editItem():
    try:
        with app.app_context():
            product_id = request.args.get('product_id')
            product = db.session.execute(db.select(Products).where(Products.id == product_id)).scalar()
            if current_user.id == product.user_id or current_user.id == 1:
                try:
                    product.desired_price = request.form.get('desired_price')
                    product.price_bellow = int(product.current_price) < int(request.form.get('desired_price'))
                except Exception as e:
                    print("Unable To edit Product, Try Again Later!", e)
                else:
                    db.session.commit()
            else:
                print("Unauthorize")
    except Exception as e:
        print(e)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

@app.route('/', methods=['GET', 'POST'])
@login_required
def index():
    form = ProductForm()
    error = None

    if request.method == 'POST':
        if form.validate_on_submit():
            try:
                name, price = seeProduct(form.amazon_url.data)
                with app.app_context():
                    new_product = Products(amazon_url=form.amazon_url.data, desired_price=form.desired_price.data, user=current_user, name=name, current_price=price, price_bellow=int(form.desired_price.data)>int(price))
                    db.session.add(new_product)
                    db.session.commit()
            except Exception as e:
                print(e)
                error = e
            else:
                return redirect("/watchlist")
        else:
            try:
                float(form.desired_price.data)
            except Exception as e:
                error = "Please enter real price"
            else:
                error = "Wrong URL address"

    return render_template("index.html", form=form, error=error)

@app.route('/all', methods=['GET', 'POST'])
@login_required
@admin_only
def all():
    form = editForm()
    data = db.session.execute(db.select(Products)).scalars().all()
    on_target = [product for product in data if product.price_bellow]
    off_target = [product for product in data if not product.price_bellow]

    if request.method == 'POST':
        if form.validate_on_submit():
            try:
                editItem()
            except Exception as e:
                print(e)
            else:
                return redirect("/all")

    return render_template('all.html', form=form, watchlist=data, on_target=on_target, off_target=off_target)

@app.route("/watchlist", methods=["GET", "POST"])
@login_required
def watchlist():
    form = editForm()

    data = current_user.products
    on_target = [product for product in data if product.price_bellow]
    off_target = [product for product in data if not product.price_bellow]

    if request.method == 'POST':
        if form.validate_on_submit():
            try:
                editItem()
            except Exception as e:
                print(e)
            else:
                return redirect("/watchlist")

    return render_template("watchlist.html", watchlist=data, on_target=on_target, off_target=off_target, form=form)

@app.route("/delete/<product_id>", methods=["GET", "POST"])
@login_required
def delete(product_id):
    product = db.session.execute(db.select(Products).where(Products.id == product_id)).scalar()
    if current_user.id == product.user_id:
        db.session.delete(product)
        db.session.commit()
    return redirect("/watchlist")

@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect("/")
    error = None
    form = LoginForm()
    if form.validate_on_submit():
        user = db.session.execute(db.select(User).where(User.email == form.email.data)).scalar()
        if user:
            if check_password_hash(user.password, form.password.data):
                login_user(user)
                return redirect("/watchlist")
            else:
                error = "Wrong Password! Try again."
        else:
            error = "User with that email does not exist"
    return render_template("login.html", form=form, error=error)

@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect("/")
    error = None
    form = RegisterForm()

    if form.validate_on_submit():
        hashed_password = generate_password_hash(
            password= form.password.data,
            method='pbkdf2:sha256',
            salt_length=8
        )
        try:
            with app.app_context():
                new_user = User(email=form.email.data, password=hashed_password)
                db.session.add(new_user)
                db.session.commit()
        except IntegrityError as e:
            error = "User with that email already exists"
        except Exception as e:
            error = "Unexpected error. Please try again later"
            print(e)
        else:
            return redirect('/')
    elif form.password.data != form.password2.data:
        error = "Passwords do not match"
    return render_template("register.html", form=form, error=error)

@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect("/login")

@app.route("/allproduct/<api_key>", methods=["GET", "POST"])
def all_products(api_key):
    if api_key == os.getenv("SECRET_API_KEY"):
        data = [product.to_dict() for product in db.session.execute(db.select(Products)).scalars().all()]
        return jsonify(data)
    else:
        return jsonify(error="Invalid API key"), 403

@app.errorhandler(404)
def page_not_found(e):
    return e, 404

if __name__ == '__main__':
    app.run(debug=True)
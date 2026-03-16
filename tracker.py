from selenium import webdriver
from selenium.webdriver.common.by import By
import time, os
from main import app, db, Products, User, seeProduct
from smtplib import SMTP
from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv())

with app.app_context():
    products = db.session.execute(db.select(Products)).scalars().all()

    for product in products:
        try:
            name, price = seeProduct(product.amazon_url)
            product.name = name
            product.current_price = price
            product.price_bellow = int(price) <= int(product.desired_price)
            if int(price) <= int(product.desired_price):
                with SMTP(os.getenv("SMTP_ADDRESS"), 587) as connection:
                    connection.starttls()
                    connection.login(user=os.getenv("SENDER_EMAIL"), password=os.getenv("SENDER_PASS"))
                    connection.sendmail(from_addr=os.getenv("SENDER_EMAIL"), to_addrs=product.user.email, msg=f"Subject: Desired Price Available!!!\n\n\n Item: {name} Is now on sale for {price}\n\n Link: {product.amazon_url}")
        except Exception as e:
            print(f"Error updating product: {product.name}, Error: {e}")
    db.session.commit()
    print("All done!")
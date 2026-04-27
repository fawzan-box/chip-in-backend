import json
from flask import Flask, request, jsonify
from sqlalchemy.orm import sessionmaker
from models import Order, engine, Session
from dotenv import load_dotenv
import os
from flask_cors import CORS
import requests
import logging
import traceback

app = Flask(__name__)

# Load the .env file
load_dotenv()  # This loads the .env file

# Load Shopify and Chip In credentials from environment variables
SHOPIFY_API_KEY = os.getenv("SHOPIFY_API_KEY")  # This is now the access token
SHOPIFY_STORE_URL = os.getenv("SHOPIFY_STORE_URL")
CHIP_IN_API_KEY = os.getenv("CHIP_IN_API_KEY")
CHIP_IN_BRAND_ID = os.getenv("CHIP_IN_BRAND_ID")


# Use the session from models.py
session = Session()

# Enable CORS for the Shopify domain
CORS(
    app,
    resources={r"/*": {"origins": "*"}},
    supports_credentials=True,
    methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)

# Setup logging to display incoming payloads
logging.basicConfig(level=logging.INFO)
logging.info(f"CHIP_IN_BRAND_ID: {CHIP_IN_BRAND_ID}")


# Function to check if the coupon is valid
def validate_shopify_coupon(coupon_code):
    url = f"{SHOPIFY_STORE_URL}/admin/api/2024-10/price_rules.json"

    headers = {
        "X-Shopify-Access-Token": SHOPIFY_API_KEY,
        "Content-Type": "application/json",
    }

    # Send a request to Shopify to get all discount codes (price rules)
    response = requests.get(url, headers=headers)
    logging.info(f"price rule response.content: {response.content}")
    if response.status_code == 200:
        price_rules = response.json().get("price_rules", [])
        logging.info(f"price rule: {price_rules}")
        for rule in price_rules:
            # Check if the coupon code matches a valid price rule
            if coupon_code == rule["title"]:
                return (
                    True,
                    rule["value"],
                    rule["value_type"],
                )  # Return the discount value

    return False, None, None  # Coupon is invalid


def calculate_price_based_on_discount(
    price,
    discount_value,
    value_type,
    override=0,
):
    logging.info(f"price {price}, dicsount {discount_value}")

    if value_type == "percentage" and override:
        discount_amount = price * discount_value / 100
        return price + discount_amount  # discount amount is in negative

    elif value_type == "percentage":
        discount_amount = price * discount_value / 100
        return price + discount_amount  # discount amount is in negative

    elif value_type == "fixed_amount":
        discount_value = discount_value * 100

        if price <= -discount_value:
            return 0.1
        else:
            return price + discount_value

    else:
        return 0


@app.route("/create-chip-in-session", methods=["POST"])
def create_chip_in_session():
    try:
        # Step 1: Get the JSON data sent from the frontend
        data = request.get_json()

        # Step 2: Extract the required fields from the incoming data
        form_type = data.get("formType")

        if form_type == "regular":
            full_name = data.get("name")
            email = data.get("email")
            phone = data.get("phone")
            shipping_address = data.get("address")
            email_marketing_consent_state = data.get(
                "email_marketing_consent_state",
                "unsubscribed",
            )
            notes = data.get(
                "notes", ""
            )  # Optional field with default value of empty string
            items = data.get("items")
            logging.info(f"order items: {items}")
            logging.info(f"form data: {data}")
            shopify_order_id = data.get("order_id")  # Capture the Shopify Order ID

            address1 = shipping_address.get("address")
            city = shipping_address.get("city")
            province = shipping_address.get("province")
            zip_code = shipping_address.get("zip")
            country = shipping_address.get("country")

            if not all([full_name, email, phone, shipping_address, items]):
                return jsonify({"error": "Missing required fields"}), 400

        elif form_type == "academy":
            player_1 = data.get("player_1")
            full_name = player_1.get("name")
            email = player_1.get("email")
            phone = player_1.get("phone")
            # shipping_address = data.get("address")
            email_marketing_consent_state = data.get(
                "email_marketing_consent_state",
                "unsubscribed",
            )
            notes = data.get(
                "notes", ""
            )  # Optional field with default value of empty string
            items = data.get("items")
            logging.info(f"order items: {items}")
            logging.info(f"form data: {data}")
            shopify_order_id = data.get("order_id") 
            address1 = player_1.get("address")
            city = player_1.get("city")
            province = player_1.get("province")
            zip_code = player_1.get("zip")
            country = player_1.get("country")
            

        

        # Step 3: Split full_name into first_name and last_name
        # name_parts = full_name.split(" ", 1)
        # first_name = name_parts[0]
        # last_name = (
        #     name_parts[1] if len(name_parts) > 1 else ""
        # )  # Handle cases where no last name is provided

        # Step 3.1: Check if all required fields are present
        

        # Step 3.2 Validate shopify coupon
        coupon_code = data.get("coupon_code", None)

        coupon_is_valid = False
        discount_value = 0
        value_type = None
        coupon_is_valid, discount_value, value_type = validate_shopify_coupon(
            coupon_code
        )
        logging.info(
            f"coup info: code {coupon_code}, valid {coupon_is_valid}, discount {discount_value}, value_type {value_type}"
        )

        # Step 4: Prepare the payload for Chip In API
        chip_in_url = "https://gate.chip-in.asia/api/v1/purchases/"

        headers = {
            "Authorization": f"Bearer {CHIP_IN_API_KEY}",
            "Content-Type": "application/json",
        }

        # Prepare the success_redirect URL with dynamic data (e.g., order_id)
        success_redirect_url = f"{SHOPIFY_STORE_URL}/pages/thank-you-page?order_id={shopify_order_id}&status=paid"

        requires_shipping = any(item.get("requires_shipping", True) for item in items)

        if requires_shipping != True:
            shipping_fee = 0
        elif country == "MY":
            if province in ["MY-12", "MY-13", "MY-15"]:
                shipping_fee = 900
            else:
                shipping_fee = 700
        else:
            shipping_fee = {
                "SG": 4000,
                "BN": 7000,
                "ID": 11000
            }.get(country, 0)

        discount_balance = 2000  # 2000 sen = 20 ringgit

        total_override = 0

        for item in items:
            # validate original line price = quantity x produce price 
            
            # validate: original_price * quantity = original_line_price
            # recheck this
            if round(float(item["original_price"]), 2) != round(float(item["original_price"]) * float(item["quantity"]), 2):
                return jsonify({"error": "Item price mismatch this"}), 400

            # validate: final_line_price = original_line_price - total_discount
            if round(float(item["final_line_price"]), 2) != round(float(item["original_line_price"]) - float(item["total_discount"]), 2):
                return jsonify({"error": "Item price mismatch that"}), 400
            
            # price = float(item["price"]) * float(item["quantity"])
            price = float(item["final_line_price"])

            if coupon_is_valid:
                calculated_item_price = calculate_price_based_on_discount(
                    price,
                    float(discount_value),
                    value_type,
                )

                if price - calculated_item_price > discount_balance:
                    calculated_item_price = price - discount_balance
                    coupon_is_valid = False

                discount_balance -= price - calculated_item_price

            else:
                calculated_item_price = price

            total_override += calculated_item_price

        total_override += shipping_fee  # shipping fee

        payload = {
            "client": {
                "email": email,
                "phone": phone,
                "full_name": full_name,  # Send full name to Chip In if required
                # "first_name": first_name,  # Optionally send first and last names separately if needed
                # "last_name": last_name,
                "shipping_street_address": address1,
                "shipping_country": country,
                "shipping_city": city,
                "shipping_zip_code": zip_code,
                "shipping_state": province,
                "state": email_marketing_consent_state,
            },
            "purchase": {
                "products": [
                    {
                        "product_id": item["product_id"],
                        "name": item["name"],
                        "price": item["original_price"],
                        "quantity": item["quantity"],
                        "category": item["variant_id"],
                        "total_discount": item["total_discount"],
                        "final_line_price": item["final_line_price"],
                        "original_line_price": item["original_line_price"],
                        "requires_shipping": item["requires_shipping"],
                    }
                    for item in items
                ],
                "total_override": total_override,
                "currency": "MYR",
                "metadata": {
                    "shopify_payload": data  # store all your custom fields here
                }
            },
            "success_redirect": success_redirect_url,  # Add the success_redirect URL here
            "notes": notes,
            "brand_id": CHIP_IN_BRAND_ID,
        }

        # Log the outgoing payload for debugging
        logging.info(f"Payload sent to Chip In API: {payload}")

        # Step 5: Send the request to Chip In API
        response = requests.post(chip_in_url, json=payload, headers=headers)
        logging.info(f"POST chip in purchase: {response.content}")
        response_data = response.json()

        # Log the response from Chip In API for debugging
        logging.info(f"Chip In API Response: {response_data}")

        # Check if the response status is successful
        if response.status_code == 201 and response_data.get("checkout_url"):
            return jsonify({"checkout_url": response_data["checkout_url"]}), 201
        else:
            return (
                jsonify(
                    {
                        "error": "Failed to create Chip In session",
                        "details": response_data,
                    }
                ),
                400,
            )
    except Exception as e:
        logging.error(f"Error processing payment: {traceback.format_exc()}")
        return jsonify({"error": str(e)}), 500


@app.route("/chipin-webhook", methods=["POST"])
def chipin_webhook():
    try:
        # Get the JSON data from the POST request
        data = request.get_json()
        logging.info(f"Received Chip In webhook event: {data}")

        # Process the webhook data (log it for now)
        if data.get("status") == "paid":
            logging.info(
                f"Payment received for Chip In order ID: {data['id']}. Creating Shopify order..."
            )
            extra = data['purchase']['metadata']['shopify_payload']['attributes']

            # Create Shopify order
            shopify_order_response = create_shopify_order(
                name=data["client"]["full_name"],
                email=data["client"]["email"],
                phone=data["client"]["phone"],
                shipping_address={
                    "address1": data["client"]["shipping_street_address"],
                    "city": data["client"]["shipping_city"],
                    "province": data["client"]["shipping_state"],
                    "zip": data["client"]["shipping_zip_code"],
                    "country": data["client"]["shipping_country"],
                    "phone": data["client"]["phone"],
                },
                items=data['purchase']['metadata']['shopify_payload']['items'],
                email_marketing_consent_state=data["client"]["state"],
                coupon_code=data['purchase']['metadata']['shopify_payload'].get('coupon_code'),
                metafields=extra,
            )

            if shopify_order_response:
                logging.info(
                    f"Shopify order created successfully: {shopify_order_response}"
                )
                return jsonify({"status": "success"}), 200
            else:
                logging.error("Failed to create Shopify order")
                return jsonify({"error": "Failed to create Shopify order"}), 400
        else:
            logging.warning(f"Chip In order status not paid: {data['status']}")
            return jsonify({"status": "ignored"}), 200
    except Exception as e:
        logging.error(f"Error processing Chip In webhook: {e}")
        return jsonify({"error": str(e)}), 500


def check_existing_webhook():
    # Check if the webhook already exists to avoid duplicating registration
    shopify_webhook_url = f"{SHOPIFY_STORE_URL}/admin/api/2024-10/webhooks.json"
    headers = {
        "X-Shopify-Access-Token": SHOPIFY_API_KEY,
        "Content-Type": "application/json",
    }

    response = requests.get(shopify_webhook_url, headers=headers)
    logging.info(f"GET shopify webhook: {response.content}")
    if response.status_code == 200:
        existing_webhooks = response.json().get("webhooks", [])
        for webhook in existing_webhooks:
            if (
                webhook["address"]
                == "https://chip-in-backend-4531.onrender.com/shopify-webhook"
                and webhook["topic"] == "orders/paid"
            ):
                logging.info("Shopify webhook already registered.")
                return True
    return False


def register_shopify_webhook():
    if check_existing_webhook():
        return  # Skip registration if the webhook already exists

    shopify_webhook_url = f"{SHOPIFY_STORE_URL}/admin/api/2024-10/webhooks.json"
    headers = {
        "X-Shopify-Access-Token": SHOPIFY_API_KEY,
        "Content-Type": "application/json",
    }

    webhook_data = {
        "webhook": {
            "topic": "orders/paid",
            "address": "https://chip-in-backend-4531.onrender.com/shopify-webhook",  # Update with your actual server URL
            "format": "json",
        }
    }

    response = requests.post(shopify_webhook_url, json=webhook_data, headers=headers)
    logging.info(f"POST shopify webhook: {response.content}")

    if response.status_code == 201:
        logging.info("Webhook registered successfully")
    else:
        logging.error(
            f"Failed to register webhook: {response.status_code}, {response.text}"
        )


@app.route("/shopify-webhook", methods=["POST"])
def shopify_webhook():
    try:
        data = request.get_json()
        logging.info(f"Received Shopify webhook event: {data}")

        # First try to get the ID at the root level
        shopify_order_id = data.get("id")

        # Get the financial status from the payload
        financial_status = data.get("financial_status")

        # Check if the financial status is 'paid'
        if financial_status == "paid":
            logging.info(f"Shopify order {shopify_order_id} has been paid.")
            return jsonify({"status": "success", "order_id": shopify_order_id}), 200
        else:
            logging.warning(
                f"Shopify order {shopify_order_id} financial status: {financial_status}"
            )
            return jsonify({"status": "ignored"}), 200

    except Exception as e:
        logging.error(f"Error processing Shopify webhook: {e}")
        return jsonify({"error": str(e)}), 500


def find_shopify_customer_by_phone(phone):
    logging.info(f"Searching for customer with phone: {phone}")
    shopify_customer_search_url = f"{SHOPIFY_STORE_URL}/admin/api/2024-10/customers/search.json?query=phone:{phone}"
    headers = {
        "X-Shopify-Access-Token": SHOPIFY_API_KEY,
        "Content-Type": "application/json",
    }
    response = requests.get(shopify_customer_search_url, headers=headers)
    logging.info(f"Customer search response: {response.content}")

    if response.status_code == 200:
        customers = response.json().get("customers", [])
        if customers:
            return customers[0]  # Return the first customer if found

    # If no customer was found, try searching without the country code
    if phone.startswith("+60"):
        phone_without_country_code = phone[3:]
        logging.info(f"Retrying search with phone number: {phone_without_country_code}")

        shopify_customer_search_url = f"{SHOPIFY_STORE_URL}/admin/api/2024-10/customers/search.json?query=phone:{phone_without_country_code}"
        response = requests.get(shopify_customer_search_url, headers=headers)
        logging.info(
            f"Customer search response (without country code): {response.content}"
        )

        if response.status_code == 200:
            customers = response.json().get("customers", [])
            if customers:
                return customers[0]  # Return the first customer if found

    return None


def find_shopify_customer_by_email(email):
    logging.info(f"Searching for customer with email: {email}")
    shopify_customer_search_url = f"{SHOPIFY_STORE_URL}/admin/api/2024-10/customers/search.json?query=email:{email}"
    headers = {
        "X-Shopify-Access-Token": SHOPIFY_API_KEY,
        "Content-Type": "application/json",
    }
    response = requests.get(shopify_customer_search_url, headers=headers)
    logging.info(f"Customer search response: {response.content}")

    if response.status_code == 200:
        customers = response.json().get("customers", [])
        if customers:
            return customers[0]  # Return the first customer if found

    return None


def create_shopify_order(
    name,
    email,
    phone,
    shipping_address,
    items,
    metafields,
    coupon_code=None,
    financial_status="paid",
    email_marketing_consent_state=None,
):
    customer = find_shopify_customer_by_email(email)

    # Shopify API URL
    shopify_order_url = f"{SHOPIFY_STORE_URL}/admin/api/2024-10/orders.json"
    shopify_customer_update_url = f"{SHOPIFY_STORE_URL}/admin/api/2024-10/customers"

    headers = {
        "X-Shopify-Access-Token": SHOPIFY_API_KEY,
        "Content-Type": "application/json",
    }

    # Split full name into first_name and last_name
    name_parts = name.split(" ", 1)
    first_name = name_parts[0]
    last_name = name_parts[1] if len(name_parts) > 1 else "."

    logging.info(f"items response: {items}")

    #Apply coupon code if any
    discount_codes = []
    if coupon_code:
        coupon_is_valid, discount_value, value_type = validate_shopify_coupon(
            coupon_code
        )
        if coupon_is_valid:
            discount_codes = [
                    {
                        "code": coupon_code,
                        "amount": abs(float(discount_value)),
                        "type": value_type
                    }
                ]

    # Shipping fee based on country and province
    requires_shipping = any(p["requires_shipping"] for p in items)

    if not requires_shipping:
        shipping_fee = 0.00
    else:
        if shipping_address['country'] == "MY":
            # Sabah, Sarawak, Labuan (MY-12 = Sabah, MY-13 = Sarawak, MY-15 = Labuan)
            if shipping_address["province"] in ["MY-12", "MY-13", "MY-15"]:
                shipping_fee = 9.00
            else:
                shipping_fee = 7.00
        elif shipping_address['country'] == "SG":
            shipping_fee = 40.00
        elif shipping_address['country'] == "BN":
            shipping_fee = 70.00
        elif shipping_address['country'] == "ID":
            shipping_fee = 110.00
        else:
            shipping_fee = 0.00  # default for other countries

    order_metafields = [
        {
            "namespace": "custom",
            "key": "player_data",
            "type": "json",
            "value": json.dumps(metafields)
        }
    ]

    if metafields['formType'] == 'academy':
        line_items = items
        class_id = update_purchase_counts( line_items, SHOPIFY_STORE_URL, headers)
        if class_id:
            print(f"Class_id metafield data: {class_id}")
            order_metafields.append(class_id)

    if customer:
        logging.info(f"Found existing customer with ID: {customer['id']}")
        # Customer exists, use the customer ID in the order payload
        order_data = {
            "order": {
                "financial_status": financial_status,
                "customer": {
                    "id": customer["id"],  # Use existing customer ID
                    "first_name": first_name,
                    "last_name": last_name,
                },
                "inventory_behaviour": "decrement_obeying_policy",
                "line_items": [
                    {
                        "product_id": item["product_id"],
                        "title": item["name"],
                        "quantity": int(float(item["quantity"])),
                        "price": item["price"] / 100,
                        "variant_id": item["variant_id"],
                        "total_discount": item.get("total_discount", 0) / 100,
                        "final_line_price": item.get("final_line_price", 0) / 100,
                        "original_line_price": item.get("original_line_price", 0) / 100

                    }
                    for item in items
                ],
                "discount_codes": discount_codes,
                "shipping_address": {
                    "first_name": first_name,
                    "last_name": last_name,
                    "address1": shipping_address["address1"],
                    "city": shipping_address["city"],
                    "province": shipping_address["province"],
                    "zip": shipping_address["zip"],
                    "country": shipping_address["country"],
                    "phone": phone,
                },
                "shipping_lines": [
                    {
                        "title": "Standard Shipping",
                        "price": str(shipping_fee),  # must be string in Shopify API
                        "code": "FlatRate",
                        "source": "Custom"
                    }
                ],
                "note": "Order created via custom payment integration",
                "metafields": order_metafields,
                "send_receipt": True,
            }
        }
    else:
        logging.info("No existing customer found, creating a new one.")
        # Customer does not exist, create a new customer in the order payload
        order_data = {
            "order": {
                "financial_status": financial_status,
                "customer": {
                    "first_name": first_name,
                    "last_name": last_name,
                    "email": email,
                },
                "inventory_behaviour": "decrement_obeying_policy",
                "line_items": [
                    {
                        "product_id": item["product_id"],
                        "title": item["name"],
                        "quantity": int(float(item["quantity"])),
                        "price": item["price"] / 100,
                        "variant_id": item["variant_id"],
                        "total_discount": item.get("total_discount", 0) / 100,
                        "final_line_price": item.get("final_line_price", 0) / 100,
                        "original_line_price": item.get("original_line_price", 0) / 100
                    }
                    for item in items
                ],
                "discount_codes": discount_codes,
                "shipping_address": {
                    "first_name": first_name,
                    "last_name": last_name,
                    "address1": shipping_address["address1"],
                    "city": shipping_address["city"],
                    "province": shipping_address["province"],
                    "zip": shipping_address["zip"],
                    "country": shipping_address["country"],
                    "phone": phone,
                },
                "shipping_lines": [
                    {
                        "title": "Standard Shipping",
                        "price": str(shipping_fee),  # must be string in Shopify API
                        "code": "FlatRate",
                        "source": "Custom"
                    }
                ],
                "note": "Order created via custom payment integration",
                "metafields": order_metafields,
                "send_receipt": True,
            }
        }

    response = requests.post(shopify_order_url, json=order_data, headers=headers)
    logging.info(f"POST shopify order url: {response.content}")

    # Log the response for debugging
    response_json = response.json()
    logging.info(f"Shopify order creation response: {response_json}")

    if response.status_code == 201:
        logging.info(f"Shopify order created successfully: {response_json}")

        logging.info(f"Email Marketing consent state: {email_marketing_consent_state}")

        # Extract the customer information from the order creation response
        created_customer = response_json.get("order", {}).get("customer", None)

        order_id = response_json.get("order", {}).get("id")
        meta_check_url = f"{SHOPIFY_STORE_URL}/admin/api/2024-10/orders/{order_id}/metafields.json"

        if created_customer:
            customer_id = created_customer["id"]
            logging.info(f"Customer ID from order response: {customer_id}")

            
            resp = requests.get(meta_check_url, headers=headers)
            print(f"resp: {resp.json()}")

            # Update email marketing consent if provided
            if email_marketing_consent_state:
                update_customer_email_consent(
                    f"{shopify_customer_update_url}/{customer_id}.json",
                    customer_id,
                    email_marketing_consent_state,
                    headers,
                )

        return response_json  # Return the created order details
    else:
        logging.error(
            f"Failed to create order in Shopify. Status Code: {response.status_code}, Response: {response.text}"
        )
        return None


def update_customer_email_consent(
    customer_update_url_template, customer_id, email_marketing_consent_state, headers
):
    logging.info(f"Updating email marketing consent for customer ID: {customer_id}")
    # Format the customer update URL with the customer ID
    customer_update_url = f"{customer_update_url_template}"
    logging.info(f"Customer update URL: {customer_update_url}")

    # Prepare the payload to update email marketing consent
    customer_data = {
        "customer": {
            "email_marketing_consent": {"state": email_marketing_consent_state}
        }
    }

    # Make the PUT request to update the customer
    response = requests.put(customer_update_url, json=customer_data, headers=headers)
    logging.info(f"Request made to Shopify: {response.status_code}, {response.text}")
    logging.info(f"Customer Email Subscription Update: {response.content}")
    if response.status_code == 200:
        logging.info(
            f"Successfully updated email marketing consent for customer ID {customer_id}"
        )
    else:
        logging.error(
            f"Failed to update email marketing consent. Status Code: {response.status_code}, Response: {response.text}"
        )


# Flask endpoint to validate the coupon
@app.route("/validate-coupon", methods=["POST"])
def validate_coupon():
    # Get the coupon code from the request body
    data = request.get_json()
    coupon_code = data.get("coupon_code")
    items = data.get("items")

    if not coupon_code:
        return jsonify({"valid": False, "message": "No coupon code provided"}), 400

    # Validate the coupon code with Shopify
    coupon_is_valid, discount_value, value_type = validate_shopify_coupon(coupon_code)

    discount_balance = 2000  # 2000 sen = 20 ringgit

    total_price_before_discount = 0
    total_price_after_discount = 0

    for item in items:
        price = float(item["price"]) * float(item["quantity"])
        total_price_before_discount += price

        if discount_balance > 0:
            calculated_item_price = calculate_price_based_on_discount(
                price,
                float(discount_value),
                value_type,
            )

            if price - calculated_item_price > discount_balance:
                calculated_item_price = price - discount_balance

            discount_balance -= price - calculated_item_price

        else:
            calculated_item_price = price

        total_price_after_discount += calculated_item_price

    if coupon_is_valid:
        return (
            jsonify(
                {
                    "valid": True,
                    "discount": discount_value,
                    "items": items,
                    "total_price_before_discount": total_price_before_discount,
                    "total_price_after_discount": total_price_after_discount,
                    "discount_value": total_price_before_discount
                    - total_price_after_discount,
                }
            ),
            200,
        )
    else:
        return jsonify({"valid": False, "message": "Invalid coupon code"}), 400
    
def update_purchase_counts(line_items, shopify_store_url, headers):
    """
    Update order metafields for purchase counts.

    Args:
        line_items (list): List of line items from the order.
        shopify_store_url (str): Your Shopify store base URL (e.g. https://yourshop.myshopify.com).
        headers (dict): Headers with access token and content type.

    Returns:
        dict: Metafield data for purchase count updates.
    """
    if not line_items:
        logging.warning("No line items found. Skipping metafield update.")
        return

    for item in line_items:
        product_id = item.get("product_id")
        quantity = item.get("quantity", 1)

        if not product_id:
            logging.warning(f"No product_id found in line item: {item}")
            continue

        metafield_url = f"{shopify_store_url}/admin/api/2024-10/products/{product_id}/metafields.json"

        # 1️⃣ Fetch existing metafields for this product
        resp = requests.get(metafield_url, headers=headers)
        if resp.status_code != 200:
            logging.warning(f"Failed to fetch metafields for product {product_id}: {resp.text}")
            continue

        product_url = f"{shopify_store_url}/admin/api/2024-10/products/{product_id}.json"
        product_resp = requests.get(product_url, headers=headers)

        if product_resp.status_code != 200:
            logging.warning(f"Failed to fetch product {product_id}: {product_resp.text}")
            continue

        product = product_resp.json().get("product", {})

        #Get product tags
        tags = product.get("tags", "")
        tags_list = [t.strip() for t in tags.split(",")]

        

        metafields = resp.json().get("metafields", [])
        existing = next(
            (m for m in metafields if m["namespace"] == "custom" and m["key"] == "purchase_count"),
            None
        )

        current_value = int(existing["value"]) if existing else 0
        new_value = current_value + quantity

        # Generate class ID based on tags and new purchase count
        class_id = parse_academy_tags(tags_list, new_value)

        # metafield_data =  {
        #     "metafield": {
        #         "namespace": "custom",
        #         "key": "purchase_count",
        #         "type": "number_integer",
        #         "value": str(new_value)
        #     }
        # }

        
        # 2️⃣ Update or create the product metafield
        if existing:
            logging.info(f"existing metafield found, updating it")
            update_url = f"{shopify_store_url}/admin/api/2024-10/metafields/{existing['id']}.json"
            update_payload = {
                "metafield": {
                    "value": str(new_value)
                }
            }
            update_resp = requests.put(update_url, headers=headers, json=update_payload)
            action = "Updated"
        else:
            logging.info(f"not existing metafield, creating new one")
            create_payload = {
                "metafield": {
                    "namespace": "custom",
                    "key": "purchase_count",
                    "type": "number_integer",
                    "value": str(new_value)
                }
            }
            update_resp = requests.post(metafield_url, headers=headers, json=create_payload)
            action = "Created"

        if update_resp.status_code in [200, 201]:
            logging.info(f"{action} purchase_count for product {product_id} to {new_value}")
            return {
            "namespace": "custom",
            "key": "class_id",
            "type": "single_line_text_field",
            "value": class_id
        }

        #     # 3️⃣ Add to the order metafields too
        #     order_meta_url = f"{shopify_store_url}/admin/api/2024-10/orders/{order_id}/metafields.json"
        #     order_meta_data = {
        #         "metafield": {
        #             "namespace": "custom",
        #             "key": f"purchase_count",
        #             "type": "number_integer",
        #             "value": new_value
        #         }
        #     }

        #     order_meta_resp = requests.post(order_meta_url, headers=headers, json=order_meta_data)

        #     if order_meta_resp.status_code in [200, 201]:
        #         logging.info(f"✅ Added purchase_count_{product_id} metafield to order {order_id} (value={new_value})")
        #     else:
        #         logging.warning(f"⚠️ Failed to create order metafield for product {product_id}: {order_meta_resp.text}")
        else:
            logging.warning(f"Failed to update metafield for product {product_id}: {update_resp.text}")

def parse_academy_tags(tags_list, purchase_count):
    batch_number = ""
    squad = ""
    code = ""
    player_number = ""

    tags = set(tags_list)

    batch_tag = next((t for t in tags if t.startswith("batch_")), "")
    if batch_tag:
        batch_number = batch_tag.replace("batch_", "")
    
    if "academy_beginner" in tags:
        code = "B"
    elif "academy_intermediate" in tags:
        code = "I"
    
    if "squad" in tags:
            squad = "SQ"
            player_number = "P"

    purchase_count_padded = str(purchase_count).zfill(3)

    class_id = f"VA{code}{batch_number}{squad}{purchase_count_padded}{player_number}"
    logging.info(f"Generated class_id: {class_id}")
    return class_id


# Start the Flask server
if __name__ == "__main__":
    register_shopify_webhook()  # Register webhook at server start if needed
    app.run(debug=True)

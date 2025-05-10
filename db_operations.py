import sqlite3
from datetime import datetime

# Import necessary variables from config_and_utils
from config_and_utils import DB_NAME, DEFAULT_LANGUAGE, logger

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    sql_create_users_table = f"""
    CREATE TABLE IF NOT EXISTS users (
        telegram_id INTEGER PRIMARY KEY, first_name TEXT, username TEXT,
        is_admin INTEGER DEFAULT 0, language_code TEXT DEFAULT '{DEFAULT_LANGUAGE}'
    )"""
    cursor.execute(sql_create_users_table)
    cursor.execute("CREATE TABLE IF NOT EXISTS products (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL, price_per_kg REAL NOT NULL, is_available INTEGER DEFAULT 1)")
    cursor.execute("CREATE TABLE IF NOT EXISTS orders (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, user_name TEXT, order_date TEXT NOT NULL, total_price REAL NOT NULL, status TEXT DEFAULT 'pending', FOREIGN KEY (user_id) REFERENCES users (telegram_id))")
    cursor.execute("CREATE TABLE IF NOT EXISTS order_items (id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER NOT NULL, product_id INTEGER NOT NULL, quantity_kg REAL NOT NULL, price_at_order REAL NOT NULL, FOREIGN KEY (order_id) REFERENCES orders (id), FOREIGN KEY (product_id) REFERENCES products (id))")
    conn.commit()
    conn.close()
    logger.info(f"Database initialized/checked at {DB_NAME}")

async def ensure_user_exists(user_id: int, first_name: str, username: str, context): # context from telegram.ext
    # We need ADMIN_IDS here. It's better if this function is in config_and_utils or takes ADMIN_IDS
    # For now, let's assume ADMIN_IDS is accessible or this logic is slightly simplified/moved.
    # To keep this file focused on DB, let's pass ADMIN_IDS if needed or handle admin check elsewhere.
    # For simplicity, I will import ADMIN_IDS here.
    from config_and_utils import ADMIN_IDS

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    is_admin_user = 1 if ADMIN_IDS and user_id in ADMIN_IDS else 0
    current_lang = DEFAULT_LANGUAGE
    try:
        cursor.execute("SELECT language_code FROM users WHERE telegram_id = ?", (user_id,))
        user_record = cursor.fetchone()
        if user_record and user_record[0]: current_lang = user_record[0]

        # context.user_data is part of the handler logic, avoid accessing it directly in db_operations
        # The caller should handle context.user_data
        # This function should primarily focus on DB write.

        cursor.execute("""
            INSERT INTO users (telegram_id, first_name, username, language_code, is_admin)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(telegram_id) DO UPDATE SET
                first_name = excluded.first_name,
                username = excluded.username,
                is_admin = excluded.is_admin,
                language_code = COALESCE(users.language_code, excluded.language_code)
        """, (user_id, first_name, username, current_lang, is_admin_user))
        conn.commit()
        logger.info(f"User {user_id} ensured in DB. Admin status: {is_admin_user}. Lang: {current_lang}")
    except sqlite3.Error as e:
        logger.error(f"DB error in ensure_user_exists for user {user_id}: {e}")
        # Return a default or raise error, let caller handle context.user_data
    finally:
        conn.close()
    return current_lang # Return the language determined/used for DB

async def set_user_language_db(user_id: int, lang_code: str):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE users SET language_code = ? WHERE telegram_id = ?", (lang_code, user_id))
        conn.commit()
        logger.info(f"User {user_id} language set to {lang_code} in DB.")
    except sqlite3.Error as e: logger.error(f"DB error in set_user_language_db for user {user_id}: {e}")
    finally: conn.close()

def add_product_to_db(name: str, price: float) -> bool:
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO products (name, price_per_kg) VALUES (?, ?)", (name, price))
        conn.commit()
        logger.info(f"Product '{name}' added to DB.")
        return True
    except sqlite3.IntegrityError:
        logger.warning(f"Attempted to add duplicate product name: {name}")
        return False
    except sqlite3.Error as e:
        logger.error(f"DB error adding product {name}: {e}")
        return False
    finally:
        conn.close()

def get_products_from_db(available_only: bool = True) -> list:
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    products = []
    try:
        query = "SELECT id, name, price_per_kg, is_available FROM products"
        if available_only:
            query += " WHERE is_available = 1"
        query += " ORDER BY name"
        cursor.execute(query)
        products = cursor.fetchall()
    except sqlite3.Error as e:
        logger.error(f"DB error getting products: {e}")
    finally:
        conn.close()
    return products

def get_product_by_id(product_id: int):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    product = None
    try:
        cursor.execute("SELECT id, name, price_per_kg, is_available FROM products WHERE id = ?", (product_id,))
        product = cursor.fetchone()
    except sqlite3.Error as e:
        logger.error(f"DB error getting product by ID {product_id}: {e}")
    finally:
        conn.close()
    return product

def update_product_in_db(product_id: int, name: str = None, price: float = None, is_available: int = None) -> bool:
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    success = False
    fields, params = [], []
    if name is not None: fields.append("name = ?"); params.append(name)
    if price is not None: fields.append("price_per_kg = ?"); params.append(price)
    if is_available is not None: fields.append("is_available = ?"); params.append(is_available)

    if not fields: conn.close(); return False

    params.append(product_id)
    query = f"UPDATE products SET {', '.join(fields)} WHERE id = ?"
    try:
        cursor.execute(query, tuple(params))
        conn.commit()
        if cursor.rowcount > 0:
            success = True
            logger.info(f"Product {product_id} updated in DB. Fields: {fields}")
    except sqlite3.Error as e:
        logger.error(f"DB error updating product {product_id}: {e}")
    finally:
        conn.close()
    return success

def delete_product_from_db(product_id: int) -> bool:
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    success = False
    try:
        cursor.execute("DELETE FROM products WHERE id = ?", (product_id,))
        conn.commit()
        if cursor.rowcount > 0:
            success = True
            logger.info(f"Product {product_id} deleted from DB.")
    except sqlite3.Error as e:
        logger.error(f"DB error deleting product {product_id}: {e}")
    finally:
        conn.close()
    return success

def save_order_to_db(user_id: int, user_name: str, cart: list, total_price: float) -> int | None:
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    order_id = None
    order_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        conn.execute("BEGIN TRANSACTION")
        cursor.execute("INSERT INTO orders (user_id, user_name, order_date, total_price, status) VALUES (?, ?, ?, ?, ?)",
                       (user_id, user_name, order_date, total_price, 'pending'))
        order_id = cursor.lastrowid
        for item in cart:
            cursor.execute("INSERT INTO order_items (order_id, product_id, quantity_kg, price_at_order) VALUES (?, ?, ?, ?)",
                           (order_id, item['id'], item['quantity'], item['price']))
        conn.commit()
        logger.info(f"Order {order_id} for user {user_id} saved to DB.")
    except sqlite3.Error as e:
        logger.error(f"Error saving order for user {user_id}: {e}")
        if conn: conn.rollback()
        order_id = None
    finally:
        if conn: conn.close()
    return order_id

def get_user_orders_from_db(user_id: int) -> list:
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    orders = []
    try:
        cursor.execute("SELECT o.id, o.order_date, o.total_price, o.status, group_concat(p.name || ' (' || oi.quantity_kg || 'kg)', CHAR(10)) FROM orders o JOIN order_items oi ON o.id = oi.order_id JOIN products p ON oi.product_id = p.id WHERE o.user_id = ? GROUP BY o.id ORDER BY o.order_date DESC", (user_id,))
        orders = cursor.fetchall()
    except sqlite3.Error as e:
        logger.error(f"DB error getting orders for user {user_id}: {e}")
    finally:
        conn.close()
    return orders

def get_all_orders_from_db() -> list:
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    orders = []
    try:
        cursor.execute("SELECT o.id, o.user_id, o.user_name, o.order_date, o.total_price, o.status, GROUP_CONCAT(p.name || ' (' || oi.quantity_kg || 'kg @ ' || oi.price_at_order || ' EUR)', CHAR(10)) as items_details FROM orders o JOIN order_items oi ON o.id = oi.order_id JOIN products p ON oi.product_id = p.id GROUP BY o.id ORDER BY o.order_date DESC")
        orders = cursor.fetchall()
    except sqlite3.Error as e:
        logger.error(f"DB error getting all orders: {e}")
    finally:
        conn.close()
    return orders

def get_shopping_list_from_db() -> list:
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    shopping_list = []
    try:
        cursor.execute("SELECT p.name, SUM(oi.quantity_kg) as total_quantity FROM order_items oi JOIN products p ON oi.product_id = p.id JOIN orders o ON oi.order_id = o.id WHERE o.status IN ('pending','confirmed') GROUP BY p.name ORDER BY p.name")
        shopping_list = cursor.fetchall()
    except sqlite3.Error as e:
        logger.error(f"DB error getting shopping list: {e}")
    finally:
        conn.close()
    return shopping_list

def delete_completed_orders_from_db() -> int:
    conn = sqlite3.connect(DB_NAME); cursor = conn.cursor(); deleted_count = 0
    try:
        cursor.execute("SELECT id FROM orders WHERE status = ?", ('completed',))
        completed_order_ids = [row[0] for row in cursor.fetchall()]
        if not completed_order_ids: conn.close(); return 0

        conn.execute("BEGIN TRANSACTION")
        for order_id_val in completed_order_ids:
            cursor.execute("DELETE FROM order_items WHERE order_id = ?", (order_id_val,))
            cursor.execute("DELETE FROM orders WHERE id = ? AND status = ?", (order_id_val, 'completed'))
            deleted_count += cursor.rowcount
        conn.commit()
        logger.info(f"Deleted {deleted_count} completed orders from DB.")
    except sqlite3.Error as e:
        logger.error(f"DB error deleting completed orders: {e}")
        if conn: conn.rollback()
        deleted_count = -1
    finally:
        if conn: conn.close()
    return deleted_count

def mark_order_as_completed_in_db(order_id_to_mark: int) -> bool:
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    success = False
    try:
        cursor.execute("UPDATE orders SET status = ? WHERE id = ?", ('completed', order_id_to_mark))
        conn.commit()
        if cursor.rowcount > 0:
            success = True
            logger.info(f"Order {order_id_to_mark} marked as completed in DB.")
    except sqlite3.Error as e:
        logger.error(f"DB error marking order {order_id_to_mark} as completed: {e}")
    finally:
        conn.close()
    return success
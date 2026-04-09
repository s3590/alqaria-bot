# database.py
import sqlite3
import logging

DATABASE_FILE = "bot_database.db"

def get_db_connection():
    """إنشاء اتصال بقاعدة البيانات."""
    conn = sqlite3.connect(DATABASE_FILE)
    conn.row_factory = sqlite3.Row  # للوصول إلى الأعمدة بالاسم
    return conn

def setup_database():
    """إعداد الجداول الأولية والبيانات الأساسية."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # --- جدول الفئات ---
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            code TEXT NOT NULL UNIQUE
        )
    ''')

    # --- جدول المنتجات ---
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            code TEXT NOT NULL UNIQUE,
            price INTEGER NOT NULL,
            delivery_fee INTEGER NOT NULL,
            is_available BOOLEAN DEFAULT 1,
            FOREIGN KEY (category_id) REFERENCES categories (id)
        )
    ''')
    
    # --- إضافة البيانات الأولية (فقط إذا كانت الجداول فارغة) ---
    cursor.execute("SELECT COUNT(*) FROM categories")
    if cursor.fetchone()[0] == 0:
        # إضافة الفئات
        categories_to_add = [
            ('دقيق وسكر', 'flour_sugar'),
            ('أرز وبقوليات', 'rice_beans'),
            ('زيوت وسمن', 'oils_ghee')
        ]
        cursor.executemany("INSERT INTO categories (name, code) VALUES (?, ?)", categories_to_add)
        
        # إضافة المنتجات
        products_to_add = [
            (1, 'كيس دقيق أبيض', 'flour_white_full', 12700, 1000),
            (1, 'كيس سكر (50 كيلو)', 'sugar_full_50kg', 19000, 1000),
            (2, 'رز الربان 5 كيلو', 'rice_raban_5kg', 3800, 200),
            (3, 'جالون زيت 4 لتر', 'oil_gallon_4l', 3750, 200)
        ]
        cursor.executemany("INSERT INTO products (category_id, name, code, price, delivery_fee) VALUES (?, ?, ?, ?, ?)", products_to_add)

    conn.commit()
    conn.close()
    logging.info("تم فحص وإعداد قاعدة البيانات بنجاح.")

# --- دوال جلب البيانات ---
def get_all_categories():
    conn = get_db_connection()
    categories = conn.execute("SELECT * FROM categories").fetchall()
    conn.close()
    return categories

def get_products_by_category(category_id):
    conn = get_db_connection()
    products = conn.execute("SELECT * FROM products WHERE category_id = ? AND is_available = 1", (category_id,)).fetchall()
    conn.close()
    return products

def get_item_details(product_id):
    conn = get_db_connection()
    product = conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
    conn.close()
    return product

# --- دوال لوحة تحكم المدير (سيتم استخدامها لاحقاً) ---
def update_product_price(product_id, new_price):
    conn = get_db_connection()
    conn.execute("UPDATE products SET price = ? WHERE id = ?", (new_price, product_id))
    conn.commit()
    conn.close()

def toggle_product_availability(product_id):
    conn = get_db_connection()
    # عكس القيمة الحالية لـ is_available
    conn.execute("UPDATE products SET is_available = 1 - is_available WHERE id = ?", (product_id,))
    conn.commit()
    conn.close()


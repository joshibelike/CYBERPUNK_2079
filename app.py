import os
import sqlite3
import json
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from flask import Flask, flash, redirect, render_template, request, session, url_for

app = Flask(__name__)
app.secret_key = 'supersecretkey_change_in_production'

UPLOAD_FOLDER = 'static/uploads/avatars'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


# БД
def get_db():
    conn = sqlite3.connect('database.db')
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_db() as conn:
        # Таблица пользователей
        conn.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                avatar TEXT DEFAULT 'uploads/avatars/default.png',
                is_admin INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        # Таблица классов
        conn.execute('''
            CREATE TABLE IF NOT EXISTS classes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                hit_dice TEXT NOT NULL,
                hp_next_level TEXT NOT NULL,
                weapon_proficiencies TEXT NOT NULL,
                save_proficiencies TEXT NOT NULL,
                skill_proficiencies TEXT NOT NULL,
                equipment TEXT NOT NULL,
                fighting_style_choice TEXT,
                second_wind TEXT
            )
        ''')
        # Таблица особенностей классов
        conn.execute('''
            CREATE TABLE IF NOT EXISTS class_features (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                class_id INTEGER NOT NULL,
                feature_name TEXT NOT NULL,
                feature_description TEXT NOT NULL,
                FOREIGN KEY (class_id) REFERENCES classes (id) ON DELETE CASCADE
            )
        ''')
        # Таблица предысторий
        conn.execute('''
            CREATE TABLE IF NOT EXISTS backgrounds (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                description TEXT NOT NULL,
                skill_profs TEXT NOT NULL,
                equipment TEXT NOT NULL,
                languages TEXT,
                feature_name TEXT NOT NULL,
                feature_description TEXT NOT NULL
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS background_choice_groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                background_id INTEGER NOT NULL,
                group_title TEXT NOT NULL,
                options_json TEXT NOT NULL,
                FOREIGN KEY (background_id) REFERENCES backgrounds (id) ON DELETE CASCADE
            )
        ''')

        conn.execute('''
            CREATE TABLE IF NOT EXISTS character_sheets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                sheet_data TEXT NOT NULL,   -- JSON со всеми полями
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
            )
        ''')
        admin = conn.execute("SELECT * FROM users WHERE username = 'admin'").fetchone()
        if not admin:
            hashed = generate_password_hash('admin123')
            conn.execute(
                "INSERT INTO users (username, email, password_hash, is_admin) VALUES (?, ?, ?, ?)",
                ('admin', 'admin@example.com', hashed, 1)
            )
        fighter = conn.execute("SELECT * FROM classes WHERE name = 'Боец'").fetchone()
        if not fighter:
            cur = conn.cursor()
            cur.execute('''
                INSERT INTO classes (name, hit_dice, hp_next_level, weapon_proficiencies, save_proficiencies, skill_proficiencies, equipment, fighting_style_choice, second_wind)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                'Боец',
                '1к10 за каждый уровень воина',
                '1к10 (или 6) + модификатор СИСТЕМА',
                'Огнестрельное оружие, Холодное оружие',
                'Система, Сила',
                'Огнестрельное оружие, Холодное оружие, Устойчивость(скр), Устойчивость(имп)',
                '(а) штурмовая винтовка и 60 патронов или (б) дробовик и 20 патронов\n(а) тяжёлый пистолет и 30 патронов или (б) два лёгких пистолета и 40 патронов\n(а) бронежилет или (б) тактическая броня\nБоевой нож, аптечка, 100 еврдолларов',
                '''Стрелок: +2 к броскам урона огнестрельным оружием
Два ствола: Когда вы атакуете двумя пистолетами, можете добавить модификатор характеристики к урону второй атаки
Тяжёлое вооружение: Вы можете перебрасывать 1 и 2 на костях урона от тяжёлого оружия (дробовик, штурмовая винтовка, пулемёт)
Рукопашник: Ваши удары без оружия и атаки холодным оружием наносят дополнительно +2 к урону
Оборонительный: Пока вы носите броню, вы получаете +1 к КБ''',
                '''Бонусное действие: Вы восстанавливаете хиты равные 1d10 + ваш уровень бойца. Использование: один раз, восстанавливается после короткого или длинного отдыха.'''
            ))
            class_id = cur.lastrowid
            conn.execute("INSERT INTO class_features (class_id, feature_name, feature_description) VALUES (?, ?, ?)",
                         (class_id, 'Боевой стиль',
                          'Вы освоили определённый подход к бою. Выберите один из вариантов выше.'))
            conn.execute("INSERT INTO class_features (class_id, feature_name, feature_description) VALUES (?, ?, ?)",
                         (class_id, 'Второе дыхание', 'Бонусное действие: восстанавливаете хиты 1d10 + уровень бойца.'))
        conn.commit()


init_db()


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


# Декораторы
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Пожалуйста, войдите в аккаунт.', 'danger')
            return redirect(url_for('account'))
        return f(*args, **kwargs)

    return decorated_function


def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Пожалуйста, войдите.', 'danger')
            return redirect(url_for('account'))
        with get_db() as conn:
            user = conn.execute("SELECT is_admin FROM users WHERE id = ?", (session['user_id'],)).fetchone()
            if not user or user['is_admin'] != 1:
                flash('Доступ запрещён. Требуются права администратора.', 'danger')
                return redirect(url_for('account'))
        return f(*args, **kwargs)

    return decorated_function


# Маршруты
@app.route('/')
def index():
    return render_template('index.html')


@app.route('/account', methods=['GET', 'POST'])
def account():
    if 'user_id' in session:
        with get_db() as conn:
            user = conn.execute("SELECT * FROM users WHERE id = ?", (session['user_id'],)).fetchone()
            if not user:
                session.clear()
                flash('Сессия устарела, войдите снова.', 'danger')
                return redirect(url_for('account'))
        if request.method == 'POST' and 'change_password' in request.form:
            current = request.form.get('current_password')
            new_pass = request.form.get('new_password')
            confirm = request.form.get('confirm_password')
            if not check_password_hash(user['password_hash'], current):
                flash('Неверный текущий пароль.', 'danger')
            elif new_pass != confirm:
                flash('Новый пароль и подтверждение не совпадают.', 'danger')
            elif len(new_pass) < 4:
                flash('Пароль должен содержать минимум 4 символа.', 'danger')
            else:
                new_hash = generate_password_hash(new_pass)
                with get_db() as conn:
                    conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (new_hash, user['id']))
                flash('Пароль успешно изменён.', 'success')
            return redirect(url_for('account'))
        if request.method == 'POST' and 'change_avatar' in request.form:
            file = request.files.get('avatar')
            if file and allowed_file(file.filename):
                filename = secure_filename(f"user_{user['id']}_{file.filename}")
                file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(file_path)
                avatar_path = f"uploads/avatars/{filename}"
                with get_db() as conn:
                    conn.execute("UPDATE users SET avatar = ? WHERE id = ?", (avatar_path, user['id']))
                flash('Аватарка обновлена!', 'success')
            else:
                flash('Недопустимый формат файла.', 'danger')
            return redirect(url_for('account'))
        is_admin = user['is_admin'] == 1
        return render_template('account.html', user=user, is_admin=is_admin, active_tab='profile')
    return render_template('account.html', active_tab='login')


@app.route('/login', methods=['POST'])
def login():
    identifier = request.form.get('login_identifier')
    password = request.form.get('password')
    if not identifier or not password:
        flash('Заполните все поля.', 'danger')
        return redirect(url_for('account'))
    with get_db() as conn:
        user = conn.execute("SELECT * FROM users WHERE email = ? OR username = ?", (identifier, identifier)).fetchone()
    if user and check_password_hash(user['password_hash'], password):
        session['user_id'] = user['id']
        session['is_admin'] = user['is_admin']
        flash(f'Добро пожаловать, {user["username"]}!', 'success')
    else:
        flash('Неверный email/имя или пароль.', 'danger')
    return redirect(url_for('account'))


@app.route('/register', methods=['POST'])
def register():
    username = request.form.get('username')
    email = request.form.get('email')
    password = request.form.get('password')
    confirm = request.form.get('confirm_password')
    avatar = request.files.get('avatar')
    if not all([username, email, password, confirm]):
        flash('Заполните все поля.', 'danger')
        return redirect(url_for('account'))
    if password != confirm:
        flash('Пароли не совпадают.', 'danger')
        return redirect(url_for('account'))
    if len(password) < 4:
        flash('Пароль должен быть не короче 4 символов.', 'danger')
        return redirect(url_for('account'))
    with get_db() as conn:
        existing = conn.execute("SELECT id FROM users WHERE email = ? OR username = ?", (email, username)).fetchone()
        if existing:
            flash('Пользователь с таким email или именем уже существует.', 'danger')
            return redirect(url_for('account'))
    avatar_path = 'uploads/avatars/default.png'
    if avatar and allowed_file(avatar.filename):
        filename = secure_filename(f"{username}_{avatar.filename}")
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        avatar.save(file_path)
        avatar_path = f"uploads/avatars/{filename}"
    password_hash = generate_password_hash(password)
    with get_db() as conn:
        conn.execute(
            "INSERT INTO users (username, email, password_hash, avatar) VALUES (?, ?, ?, ?)",
            (username, email, password_hash, avatar_path)
        )
        user = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        session['user_id'] = user['id']
        session['is_admin'] = user['is_admin']
    flash('Регистрация успешна!', 'success')
    return redirect(url_for('account'))


@app.route('/logout')
def logout():
    session.clear()
    flash('Вы вышли из аккаунта.', 'info')
    return redirect(url_for('account'))


# Админ-панель
@app.route('/admin')
@admin_required
def admin_panel():
    with get_db() as conn:
        users = conn.execute("SELECT id, username, email, is_admin FROM users ORDER BY id").fetchall()
    return render_template('admin.html', users=users)


@app.route('/admin/toggle_admin/<int:user_id>')
@admin_required
def toggle_admin(user_id):
    if user_id == session['user_id']:
        flash('Нельзя изменить свой статус.', 'danger')
        return redirect(url_for('admin_panel'))
    with get_db() as conn:
        user = conn.execute("SELECT is_admin FROM users WHERE id = ?", (user_id,)).fetchone()
        if user:
            new_status = 0 if user['is_admin'] else 1
            conn.execute("UPDATE users SET is_admin = ? WHERE id = ?", (new_status, user_id))
            flash('Статус изменён.', 'success')
    return redirect(url_for('admin_panel'))


# Управление классами
@app.route('/classes')
def show_classes():
    with get_db() as conn:
        classes = conn.execute("SELECT * FROM classes ORDER BY id").fetchall()
        classes_with_features = []
        for cls in classes:
            features = conn.execute("SELECT feature_name, feature_description FROM class_features WHERE class_id = ?",
                                    (cls['id'],)).fetchall()
            classes_with_features.append({'class': cls, 'features': features})
    return render_template('classes.html', classes=classes_with_features)


@app.route('/admin/add_class', methods=['GET', 'POST'])
@admin_required
def add_class():
    if request.method == 'POST':
        name = request.form['name'].strip()
        # Проверка уникальности
        with get_db() as conn:
            existing = conn.execute("SELECT id FROM classes WHERE name = ?", (name,)).fetchone()
            if existing:
                flash('Класс с таким названием уже существует!', 'danger')
                return render_template('add_class.html')

        hit_dice = request.form['hit_dice']
        hp_next_level = request.form['hp_next_level']
        weapon_profs = request.form['weapon_proficiencies']
        save_profs = request.form['save_proficiencies']
        skill_profs = request.form['skill_proficiencies']
        equipment = request.form['equipment']
        fighting_style = request.form.get('fighting_style_choice', '')
        second_wind = request.form.get('second_wind', '')

        with get_db() as conn:
            cur = conn.cursor()
            cur.execute('''
                INSERT INTO classes (name, hit_dice, hp_next_level, weapon_proficiencies, save_proficiencies, skill_proficiencies, equipment, fighting_style_choice, second_wind)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (name, hit_dice, hp_next_level, weapon_profs, save_profs, skill_profs, equipment, fighting_style,
                  second_wind))
            class_id = cur.lastrowid
            feature_names = request.form.getlist('feature_name[]')
            feature_descs = request.form.getlist('feature_description[]')
            for fn, fd in zip(feature_names, feature_descs):
                if fn.strip():
                    conn.execute(
                        "INSERT INTO class_features (class_id, feature_name, feature_description) VALUES (?, ?, ?)",
                        (class_id, fn, fd))
            conn.commit()
        flash(f'Класс "{name}" успешно добавлен!', 'success')
        return redirect(url_for('show_classes'))
    return render_template('add_class.html')


# Управление предысториями
@app.route('/backgrounds')
def show_backgrounds():
    with get_db() as conn:
        bgs = conn.execute("SELECT * FROM backgrounds ORDER BY id").fetchall()
        bgs_with_groups = []
        for bg in bgs:
            groups = conn.execute(
                "SELECT group_title, options_json FROM background_choice_groups WHERE background_id = ?",
                (bg['id'],)).fetchall()
            bgs_with_groups.append({'background': bg, 'choice_groups': groups})
    return render_template('backgrounds.html', backgrounds=bgs_with_groups)


@app.route('/admin/add_background', methods=['GET', 'POST'])
@admin_required
def add_background():
    if request.method == 'POST':
        name = request.form['name'].strip()
        with get_db() as conn:
            existing = conn.execute("SELECT id FROM backgrounds WHERE name = ?", (name,)).fetchone()
            if existing:
                flash('Предыстория с таким названием уже существует!', 'danger')
                return render_template('add_background.html')

        description = request.form['description']
        skill_profs = request.form['skill_proficiencies']
        equipment = request.form['equipment']
        languages = request.form.get('languages', '')
        feature_name = request.form['feature_name']
        feature_desc = request.form['feature_description']

        with get_db() as conn:
            cur = conn.cursor()
            cur.execute('''
                INSERT INTO backgrounds (name, description, skill_profs, equipment, languages, feature_name, feature_description)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (name, description, skill_profs, equipment, languages, feature_name, feature_desc))
            bg_id = cur.lastrowid
            group_titles = request.form.getlist('group_title[]')
            group_options = request.form.getlist('group_options[]')
            for title, opts_str in zip(group_titles, group_options):
                if title.strip() and opts_str.strip():
                    options_list = []
                    for line in opts_str.strip().split('\n'):
                        if ':' in line:
                            parts = line.split(':', 1)
                            opt_name = parts[0].strip()
                            opt_bonus = parts[1].strip()
                            options_list.append({'name': opt_name, 'bonus': opt_bonus})
                    if options_list:
                        conn.execute(
                            "INSERT INTO background_choice_groups (background_id, group_title, options_json) VALUES (?, ?, ?)",
                            (bg_id, title, json.dumps(options_list, ensure_ascii=False)))
            conn.commit()
        flash(f'Предыстория "{name}" добавлена!', 'success')
        return redirect(url_for('show_backgrounds'))
    return render_template('add_background.html')


@app.route('/sheets')
@login_required
def sheets_list():
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, name, sheet_data, updated_at FROM character_sheets WHERE user_id = ? ORDER BY updated_at DESC",
            (session['user_id'],)
        ).fetchall()

    sheets = []
    for row in rows:
        data = json.loads(row['sheet_data'])
        sheets.append({
            'id': row['id'],
            'name': data.get('name', 'Без имени'),
            'class': data.get('class', 'Не указан'),
            'level': data.get('level', 1),
            'updated': row['updated_at']
        })
    return render_template('sheets_list.html', sheets=sheets)

@app.route('/sheet/new', methods=['GET', 'POST'])
@login_required
def new_sheet():
    if request.method == 'POST':
        name = request.form.get('name', 'Персонаж')
        empty_sheet = {
            'name': name,
            'class': '',
            'background': '',
            'level': 1,
            'race': '',
            'alignment': '',
            'photo': '',
            'stats': {
                'strength': 10,
                'system': 10,
                'dexterity': 10,
                'wisdom': 10,
                'charisma': 10,
                'intelligence': 10
            },
            'hp_max': 0,
            'hp_current': 0,
            'hit_dice': '',
            'armor_class': 10,
            'speed': 30,
            'initiative': 0,
            'proficiency_bonus': 2,
            'skills': [
                {'name': 'Эго', 'stat': 'charisma', 'proficient': False, 'expertise': False},
                {'name': 'Присутствие', 'stat': 'charisma', 'proficient': False, 'expertise': False},
                {'name': 'Соц. рейтинг', 'stat': 'intelligence', 'proficient': False, 'expertise': False},
                {'name': 'Проворство', 'stat': 'dexterity', 'proficient': False, 'expertise': False},
                {'name': 'Реакция', 'stat': 'dexterity', 'proficient': False, 'expertise': False},
                {'name': 'Скрытность', 'stat': 'dexterity', 'proficient': False, 'expertise': False},
                {'name': 'Внимательность', 'stat': 'wisdom', 'proficient': False, 'expertise': False},
                {'name': 'Хладнокровие', 'stat': 'wisdom', 'proficient': False, 'expertise': False},
                {'name': 'Техника', 'stat': 'intelligence', 'proficient': False, 'expertise': False},
                {'name': 'Медицина', 'stat': 'intelligence', 'proficient': False, 'expertise': False},
                {'name': 'Наука', 'stat': 'intelligence', 'proficient': False, 'expertise': False},
                {'name': 'Огнестрел. оружие', 'stat': 'system', 'proficient': False, 'expertise': False},
                {'name': 'Холодное оружие', 'stat': 'strength', 'proficient': False, 'expertise': False},
                {'name': 'Устойчивость(имп)', 'stat': 'constitution', 'proficient': False, 'expertise': False},
                {'name': 'Устойчивость(скр)', 'stat': 'constitution', 'proficient': False, 'expertise': False}
            ],
            'languages': '',
            'features': '',
            'equipment': '',
            'notes': ''
        }
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO character_sheets (user_id, name, sheet_data) VALUES (?, ?, ?)",
                (session['user_id'], name, json.dumps(empty_sheet))
            )
            sheet_id = cur.lastrowid
        return redirect(url_for('sheet_edit', sheet_id=sheet_id))
    return render_template('sheet_new.html')


@app.route('/sheet/<int:sheet_id>', methods=['GET', 'POST'])
@login_required
def sheet_edit(sheet_id):
    with get_db() as conn:
        row = conn.execute(
            "SELECT id, sheet_data FROM character_sheets WHERE id = ? AND user_id = ?",
            (sheet_id, session['user_id'])
        ).fetchone()
        if not row:
            flash('Лист не найден.', 'danger')
            return redirect(url_for('sheets_list'))

    sheet = json.loads(row['sheet_data'])

    if request.method == 'POST':
        new_sheet = request.get_json()
        if new_sheet:
            with get_db() as conn:
                conn.execute(
                    "UPDATE character_sheets SET sheet_data = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (json.dumps(new_sheet), sheet_id)
                )
            return {'status': 'ok'}
        else:
            flash('Не удалось сохранить.', 'danger')

    return render_template('sheet_edit.html', sheet_id=sheet_id, sheet=sheet)

@app.route('/sheet/<int:sheet_id>/delete', methods=['POST'])
@login_required
def delete_sheet(sheet_id):
    with get_db() as conn:
        sheet = conn.execute(
            "SELECT id FROM character_sheets WHERE id = ? AND user_id = ?",
            (sheet_id, session['user_id'])
        ).fetchone()
        if sheet:
            conn.execute("DELETE FROM character_sheets WHERE id = ?", (sheet_id,))
            flash('Персонаж удалён.', 'success')
        else:
            flash('Ошибка: лист не найден.', 'danger')
    return redirect(url_for('sheets_list'))

@app.route('/admin/delete_class/<int:class_id>')
@admin_required
def delete_class(class_id):
    with get_db() as conn:
        cls = conn.execute("SELECT id FROM classes WHERE id = ?", (class_id,)).fetchone()
        if cls:
            conn.execute("DELETE FROM classes WHERE id = ?", (class_id,))
            flash('Класс удалён.', 'success')
        else:
            flash('Класс не найден.', 'danger')
    return redirect(url_for('show_classes'))

@app.route('/admin/delete_background/<int:bg_id>')
@admin_required
def delete_background(bg_id):
    with get_db() as conn:
        bg = conn.execute("SELECT id FROM backgrounds WHERE id = ?", (bg_id,)).fetchone()
        if bg:
            conn.execute("DELETE FROM backgrounds WHERE id = ?", (bg_id,))
            flash('Предыстория удалена.', 'success')
        else:
            flash('Предыстория не найдена.', 'danger')
    return redirect(url_for('show_backgrounds'))


if __name__ == '__main__':
    app.run(debug=True)
import sqlite3
import os
import time
import json
import threading
import datetime
from flask import Flask, render_template, request, redirect, url_for, session, flash, send_from_directory
from flask_socketio import SocketIO, emit
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.config['SECRET_KEY'] = 'super_secret_key_123' 
socketio = SocketIO(app, cors_allowed_origins="*")

app.config['UPLOAD_FOLDER'] = 'static/uploads'
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True) 

online_users = {}
active_calls = {}

def init_db():
    with sqlite3.connect('chat.db', timeout=10) as conn:
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE, password TEXT, avatar TEXT DEFAULT '/static/WS.jpg', bio TEXT DEFAULT 'Available')''')
        c.execute('''CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY AUTOINCREMENT, sender TEXT, recipient TEXT, message TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS custom_groups (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, members TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS blocked_users (id INTEGER PRIMARY KEY AUTOINCREMENT, blocker TEXT, blocked TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS reels (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, video_url TEXT, caption TEXT, views INTEGER DEFAULT 0)''')
        c.execute('''CREATE TABLE IF NOT EXISTS reel_comments (id INTEGER PRIMARY KEY AUTOINCREMENT, reel_id INTEGER, username TEXT, comment TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
        c.execute('''CREATE TABLE IF NOT EXISTS calls (id INTEGER PRIMARY KEY AUTOINCREMENT, caller TEXT, receiver TEXT, call_type TEXT, status TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
        c.execute('''CREATE TABLE IF NOT EXISTS statuses (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, media_url TEXT, caption TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
        c.execute('''CREATE TABLE IF NOT EXISTS friendships (id INTEGER PRIMARY KEY AUTOINCREMENT, sender TEXT, receiver TEXT, status TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS scheduled_messages (id INTEGER PRIMARY KEY AUTOINCREMENT, sender TEXT, recipient TEXT, message TEXT, send_at DATETIME, status TEXT DEFAULT 'pending')''')

        # Safely add new columns if they don't exist yet
        try: c.execute("ALTER TABLE messages ADD COLUMN is_read INTEGER DEFAULT 0")
        except sqlite3.OperationalError: pass
            
        try: c.execute("ALTER TABLE calls ADD COLUMN is_read INTEGER DEFAULT 0")
        except sqlite3.OperationalError: pass

        try: c.execute("ALTER TABLE statuses ADD COLUMN viewers TEXT DEFAULT ''")
        except sqlite3.OperationalError: pass

        try: c.execute("ALTER TABLE messages ADD COLUMN reactions TEXT DEFAULT '{}'")
        except sqlite3.OperationalError: pass

        try: c.execute("ALTER TABLE users ADD COLUMN is_private INTEGER DEFAULT 0")
        except sqlite3.OperationalError: pass

        try: c.execute("ALTER TABLE users ADD COLUMN win_streak INTEGER DEFAULT 0")
        except sqlite3.OperationalError: pass

        # Columns for Reel Likes & Audio
        try: c.execute("ALTER TABLE reels ADD COLUMN likes INTEGER DEFAULT 0")
        except sqlite3.OperationalError: pass

        try: c.execute("ALTER TABLE reels ADD COLUMN liked_by TEXT DEFAULT ''")
        except sqlite3.OperationalError: pass

        try: c.execute("ALTER TABLE reels ADD COLUMN audio_title TEXT DEFAULT 'Original Audio'")
        except sqlite3.OperationalError: pass

        try: c.execute("ALTER TABLE reels ADD COLUMN comments_count INTEGER DEFAULT 0")
        except sqlite3.OperationalError: pass

        # Columns for Group Profile & Admin
        try: c.execute("ALTER TABLE custom_groups ADD COLUMN admin TEXT DEFAULT ''")
        except sqlite3.OperationalError: pass

        try: c.execute("ALTER TABLE custom_groups ADD COLUMN avatar TEXT DEFAULT '/static/WS.jpg'")
        except sqlite3.OperationalError: pass

        try: c.execute("ALTER TABLE custom_groups ADD COLUMN description TEXT DEFAULT 'Group Community'")
        except sqlite3.OperationalError: pass

        # Columns for Enhanced Statuses
        try: c.execute("ALTER TABLE statuses ADD COLUMN bg_style TEXT DEFAULT 'gradient-1'")
        except sqlite3.OperationalError: pass

        try: c.execute("ALTER TABLE statuses ADD COLUMN font_style TEXT DEFAULT 'sans-serif'")
        except sqlite3.OperationalError: pass

        try: c.execute("ALTER TABLE statuses ADD COLUMN music_url TEXT DEFAULT ''")
        except sqlite3.OperationalError: pass

        # Columns for Master Admin & Account Freezing
        try: c.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER DEFAULT 0")
        except sqlite3.OperationalError: pass

        try: c.execute("ALTER TABLE users ADD COLUMN is_frozen INTEGER DEFAULT 0")
        except sqlite3.OperationalError: pass

        # System Reports & Moderation Table
        c.execute('''CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            reporter TEXT,
            target_type TEXT,
            target_id TEXT,
            reason TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            status TEXT DEFAULT 'pending'
        )''')

        # Guarantee Master Admin X13 with password Anas@1013 exists
        admin_user = "x13"
        admin_pass_hash = generate_password_hash("Anas@1013")
        c.execute("SELECT id FROM users WHERE username=?", (admin_user,))
        existing_admin = c.fetchone()
        if existing_admin:
            c.execute("UPDATE users SET password=?, is_admin=1, is_frozen=0 WHERE username=?", (admin_pass_hash, admin_user))
        else:
            c.execute("INSERT INTO users (username, password, avatar, bio, is_admin, is_frozen) VALUES (?, ?, ?, ?, ?, ?)",
                      (admin_user, admin_pass_hash, '/static/WS.jpg', '👑 Master System Administrator', 1, 0))

        conn.commit()

init_db()

@app.route('/sw.js')
def sw():
    return send_from_directory('static', 'sw.js', mimetype='application/javascript')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        # Force username to lowercase to prevent duplicates
        username = request.form['username'].strip().lower()
        password = request.form['password']
        hashed_pw = generate_password_hash(password) 
        try:
            with sqlite3.connect('chat.db', timeout=10) as conn:
                c = conn.cursor()
                c.execute("SELECT COUNT(*) FROM users")
                total_users = c.fetchone()[0]
                # Auto-grant admin rights if first user or username is admin
                is_admin = 1 if (total_users == 0 or username == 'admin') else 0
                
                c.execute("INSERT INTO users (username, password, avatar, bio, is_admin) VALUES (?, ?, '/static/WS.jpg', 'Available', ?)", (username, hashed_pw, is_admin))
                conn.commit()
            flash("Account created successfully! Please log in.")
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            flash("Username already exists! Try another.")
            return redirect(url_for('register'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        # Force username to lowercase to match registration
        username = request.form['username'].strip().lower()
        password = request.form['password']
        with sqlite3.connect('chat.db', timeout=10) as conn:
            c = conn.cursor()
            c.execute("SELECT password, is_frozen, is_admin FROM users WHERE username=?", (username,))
            user = c.fetchone()
        
        if user:
            hashed_pw, is_frozen, is_admin = user[0], user[1], user[2]
            if check_password_hash(hashed_pw, password):
                if is_frozen:
                    flash("⛔ Account Frozen: Your account has been suspended by System Admin.")
                    return redirect(url_for('login'))
                session['username'] = username 
                session['is_admin'] = bool(is_admin)
                return redirect(url_for('index'))
        flash("Invalid Username or Password!")
        return redirect(url_for('login'))
    return render_template('login.html')

SECRET_ADMIN_PASSCODE = "7796" # Master Secret Admin Security PIN
SECRET_ADMIN_TOKEN = "WS_MASTER_KEY_7796"

@app.route('/secret-admin-login', methods=['GET', 'POST'])
@app.route('/admin-login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip().lower()
        password = request.form.get('password', '')

        # STRICT WHITELIST: Only Master Admin username X13 can log in as Admin!
        if username != "x13":
            flash("⛔ ACCESS DENIED: Only Master Admin authorized to access Admin Portal!")
            return render_template('admin_login.html')

        with sqlite3.connect('chat.db', timeout=10) as conn:
            c = conn.cursor()
            c.execute("SELECT password, is_frozen, is_admin FROM users WHERE username='x13'")
            user = c.fetchone()

        if user:
            hashed_pw, is_frozen, is_admin = user[0], user[1], user[2]
            if check_password_hash(hashed_pw, password) or password == "Anas@1013":
                session['username'] = "x13"
                session['is_admin'] = True

                with sqlite3.connect('chat.db', timeout=10) as conn:
                    c = conn.cursor()
                    c.execute("UPDATE users SET is_admin=1 WHERE username='x13'")
                    conn.commit()

                return redirect(url_for('admin_portal'))

        flash("⛔ Invalid Password for Master Admin!")
        return render_template('admin_login.html')

    return render_template('admin_login.html')

@app.route('/secret-admin-portal-7796', methods=['GET', 'POST'])
@app.route('/admin-direct-access', methods=['GET', 'POST'])
@app.route('/admin', methods=['GET', 'POST'])
def admin_portal():
    if 'username' not in session:
        return redirect(url_for('admin_login'))
    
    username = session['username'].strip().lower()
    
    # STRICT MASTER ADMIN GUARD: ONLY X13 CAN ACCESS ADMIN PORTAL!
    if username != "x13":
        flash("⛔ ACCESS DENIED: Only Master Admin authorized to access Admin Portal!")
        return redirect(url_for('admin_login'))

    # Ensure user has is_admin=1 in DB and fetch all moderation records
    with sqlite3.connect('chat.db', timeout=10) as conn:
        c = conn.cursor()
        c.execute("UPDATE users SET is_admin=1 WHERE username='x13'")
        
        c.execute("SELECT id, reporter, target_type, target_id, reason, timestamp, status FROM reports ORDER BY id DESC")
        reports = [{'id': r[0], 'reporter': r[1], 'target_type': r[2], 'target_id': r[3], 'reason': r[4], 'timestamp': r[5], 'status': r[6]} for r in c.fetchall()]

        c.execute("SELECT id, username, avatar, bio, is_admin, is_frozen, win_streak FROM users ORDER BY id DESC")
        users = [{'id': r[0], 'username': r[1], 'avatar': r[2] or '/static/WS.jpg', 'bio': r[3] or '', 'is_admin': r[4] or 0, 'is_frozen': r[5] or 0, 'win_streak': r[6] or 0} for r in c.fetchall()]

        c.execute("SELECT id, username, video_url, caption, views, likes FROM reels ORDER BY id DESC")
        reels = [{'id': r[0], 'username': r[1], 'video_url': r[2], 'caption': r[3], 'views': r[4], 'likes': r[5]} for r in c.fetchall()]

        c.execute("SELECT COUNT(*) FROM users")
        total_users = c.fetchone()[0]

        c.execute("SELECT COUNT(*) FROM users WHERE is_frozen = 1")
        frozen_users = c.fetchone()[0]

        c.execute("SELECT COUNT(*) FROM reels")
        total_reels = c.fetchone()[0]

        c.execute("SELECT COUNT(*) FROM messages")
        total_messages = c.fetchone()[0]

        conn.commit()

    return render_template('admin.html', username=username, reports=reports, users=users, reels=reels, total_users=total_users, frozen_users=frozen_users, total_reels=total_reels, total_messages=total_messages)

@app.route('/logout')
def logout():
    session.pop('username', None) 
    return redirect(url_for('login'))

@app.route('/')
def index():
    if 'username' not in session: return redirect(url_for('login'))
    username = session['username']
    
    with sqlite3.connect('chat.db', timeout=10) as conn:
        c = conn.cursor()
        c.execute("SELECT avatar, bio FROM users WHERE username=?", (username,))
        row = c.fetchone()
        avatar = row[0] if row and row[0] else '/static/WS.jpg'
        bio = row[1] if row and row[1] else 'Available'
        
    return render_template('index.html', my_name=username, my_avatar=avatar, my_bio=bio)

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files: return "No file", 400
    file = request.files['file']
    if file.filename == '': return "No file selected", 400
    if file:
        original_name = secure_filename(file.filename)
        filename = f"{int(time.time())}_{original_name}"
        
        # 1. Filepath for saving to the local Windows/Mac/Linux system
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        
        # 2. URL path for the web browser (MUST manually use forward slashes)
        web_url = f"/static/uploads/{filename}"
        
        return f"{web_url}|{original_name}", 200

@app.route('/block_user', methods=['POST'])
def block_user():
    blocker = session.get('username')
    blocked = request.form.get('target')
    if not blocker or not blocked: return "Error", 400
    with sqlite3.connect('chat.db', timeout=10) as conn:
        c = conn.cursor()
        c.execute("INSERT INTO blocked_users (blocker, blocked) VALUES (?, ?)", (blocker, blocked))
        conn.commit()
    return "OK", 200

@app.route('/unblock_user', methods=['POST'])
def unblock_user():
    blocker = session.get('username')
    blocked = request.form.get('target')
    if not blocker or not blocked: return "Error", 400
    with sqlite3.connect('chat.db', timeout=10) as conn:
        c = conn.cursor()
        c.execute("DELETE FROM blocked_users WHERE blocker=? AND blocked=?", (blocker, blocked))
        conn.commit()
    return "OK", 200

@app.route('/leave_group', methods=['POST'])
def leave_group():
    username = session.get('username')
    group_id_str = request.form.get('group_id')
    if not username or not group_id_str: return "Error", 400
    
    group_id = group_id_str.replace("GROUP_", "")
    with sqlite3.connect('chat.db', timeout=10) as conn:
        c = conn.cursor()
        c.execute("SELECT members FROM custom_groups WHERE id=?", (group_id,))
        row = c.fetchone()
        if row:
            members = row[0].split(',')
            if username in members:
                members.remove(username)
                if len(members) > 0:
                    c.execute("UPDATE custom_groups SET members=? WHERE id=?", (",".join(members), group_id))
                else:
                    c.execute("DELETE FROM custom_groups WHERE id=?", (group_id,))
            conn.commit()
    return "OK", 200

@socketio.on('register')
def handle_register(username):
    online_users[username] = request.sid
    with sqlite3.connect('chat.db', timeout=10) as conn:
        c = conn.cursor()
        c.execute("SELECT blocked FROM blocked_users WHERE blocker=?", (username,))
        blocked_by_me = [row[0] for row in c.fetchall()]

        c.execute("SELECT username FROM users")
        all_users = [row[0] for row in c.fetchall()]

        c.execute("SELECT username, avatar, bio, is_private, win_streak FROM users")
        profiles = {row[0]: {'avatar': row[1] or '/static/WS.jpg', 'bio': row[2] or 'Available', 'is_private': row[3] or 0, 'win_streak': row[4] or 0} for row in c.fetchall()}

        c.execute("SELECT id, name, members, admin, avatar, description FROM custom_groups")
        my_groups = []
        for g in c.fetchall():
            member_list = g[2].split(',')
            if username in member_list:
                admin_name = g[3] or (member_list[0] if member_list else '')
                group_avatar = g[4] or '/static/WS.jpg'
                group_desc = g[5] or 'Group Community'
                my_groups.append({
                    'id': f"GROUP_{g[0]}", 
                    'name': g[1], 
                    'members': member_list,
                    'admin': admin_name,
                    'avatar': group_avatar,
                    'description': group_desc
                })
                
        c.execute("SELECT COUNT(*) FROM calls WHERE receiver=? AND status='Missed' AND is_read=0", (username,))
        unread_calls = c.fetchone()[0]

        # Fetch personal friendships
        c.execute("SELECT sender, receiver, status FROM friendships WHERE sender=? OR receiver=?", (username, username))
        friendships = [{'sender': row[0], 'receiver': row[1], 'status': row[2]} for row in c.fetchall()]

    emit('update_users', {'contacts': all_users, 'online': list(online_users.keys()), 'groups': my_groups, 'blocked': blocked_by_me, 'profiles': profiles}, broadcast=True)
    
    # Send friendships to the specific user
    emit('load_friendships', friendships, room=request.sid)

    group_ids = [g['id'] for g in my_groups]
    query = '''SELECT id, sender, recipient, message, is_read, reactions FROM messages 
               WHERE (recipient = "" OR recipient IS NULL OR recipient = ? OR sender = ?)'''
    params = [username, username]
    if group_ids:
        placeholders = ','.join(['?'] * len(group_ids))
        query += f" OR recipient IN ({placeholders})"
        params.extend(group_ids)
        
    with sqlite3.connect('chat.db', timeout=10) as conn:
        c = conn.cursor()
        c.execute(query, params)
        history = [{'id': row[0], 'user': row[1], 'recipient': row[2] if row[2] else None, 'message': row[3], 'is_read': row[4], 'reactions': json.loads(row[5]) if row[5] else {}} for row in c.fetchall()]
    
    emit('load_history', history, room=request.sid)
    emit('unread_calls_count', unread_calls, room=request.sid) 

@socketio.on('add_reaction')
def handle_add_reaction(data):
    msg_id = data['msg_id']
    reaction = data['reaction']
    username = data['username']
    
    with sqlite3.connect('chat.db', timeout=10) as conn:
        c = conn.cursor()
        c.execute("SELECT reactions FROM messages WHERE id=?", (msg_id,))
        row = c.fetchone()
        if row:
            try: reactions_dict = json.loads(row[0]) if row[0] else {}
            except json.JSONDecodeError: reactions_dict = {}
            
            # Toggle reaction
            if reactions_dict.get(username) == reaction:
                del reactions_dict[username]
            else:
                reactions_dict[username] = reaction
                
            c.execute("UPDATE messages SET reactions=? WHERE id=?", (json.dumps(reactions_dict), msg_id))
            conn.commit()
            
            emit('reaction_updated', {'msg_id': msg_id, 'reactions': reactions_dict}, broadcast=True)

@socketio.on('mark_read')
def handle_mark_read(data):
    sender = data.get('sender')
    recipient = data.get('recipient')
    if sender and recipient:
        with sqlite3.connect('chat.db', timeout=10) as conn:
            c = conn.cursor()
            c.execute("UPDATE messages SET is_read = 1 WHERE sender = ? AND recipient = ?", (sender, recipient))
            conn.commit()
        if sender in online_users:
            emit('messages_read', {'reader': recipient}, room=online_users[sender])

@socketio.on('update_profile')
def handle_update_profile(data):
    username = data.get('username')
    avatar = data.get('avatar')
    bio = data.get('bio')
    with sqlite3.connect('chat.db', timeout=10) as conn:
        c = conn.cursor()
        c.execute("UPDATE users SET avatar=?, bio=? WHERE username=?", (avatar, bio, username))
        conn.commit()
    emit('profile_updated', {'username': username, 'avatar': avatar, 'bio': bio}, broadcast=True)

@socketio.on('create_group')
def handle_create_group(data):
    name = data['name']
    members = ",".join(data['members'])
    admin = data.get('creator') or (data['members'][-1] if data['members'] else '')
    avatar = data.get('avatar') or '/static/WS.jpg'
    description = data.get('description') or 'Group Community'
    
    with sqlite3.connect('chat.db', timeout=10) as conn:
        c = conn.cursor()
        c.execute("INSERT INTO custom_groups (name, members, admin, avatar, description) VALUES (?, ?, ?, ?, ?)", (name, members, admin, avatar, description))
        group_id = c.lastrowid
        conn.commit()
    
    group_data = {
        'id': f"GROUP_{group_id}", 
        'name': name, 
        'members': data['members'],
        'admin': admin,
        'avatar': avatar,
        'description': description
    }
    for member in data['members']:
        if member in online_users:
            emit('group_added', group_data, room=online_users[member])

@socketio.on('update_group_profile')
def handle_update_group_profile(data):
    group_id_str = data.get('group_id')
    if not group_id_str: return
    group_id = group_id_str.replace("GROUP_", "")
    updater = data.get('username')
    new_name = data.get('name')
    new_avatar = data.get('avatar')
    new_description = data.get('description')
    
    with sqlite3.connect('chat.db', timeout=10) as conn:
        c = conn.cursor()
        c.execute("SELECT admin, members FROM custom_groups WHERE id=?", (group_id,))
        row = c.fetchone()
        if row:
            admin_str = row[0]
            members = row[1].split(',')
            admin_list = [a.strip() for a in (admin_str or '').split(',') if a.strip()]
            if not admin_list and members: admin_list = [members[0]]
            
            if updater in admin_list:
                c.execute("UPDATE custom_groups SET name=?, avatar=?, description=? WHERE id=?", (new_name, new_avatar, new_description, group_id))
                conn.commit()
                
                updated_data = {
                    'id': group_id_str,
                    'name': new_name,
                    'avatar': new_avatar,
                    'description': new_description,
                    'admin': ",".join(admin_list),
                    'members': members
                }
                
                for member in members:
                    if member in online_users:
                        emit('group_profile_updated', updated_data, room=online_users[member])

@socketio.on('toggle_group_admin')
def handle_toggle_group_admin(data):
    group_id_str = data.get('group_id')
    if not group_id_str: return
    group_id = group_id_str.replace("GROUP_", "")
    requester = data.get('username')
    target_user = data.get('target_user')
    action = data.get('action')
    
    with sqlite3.connect('chat.db', timeout=10) as conn:
        c = conn.cursor()
        c.execute("SELECT name, members, admin, avatar, description FROM custom_groups WHERE id=?", (group_id,))
        row = c.fetchone()
        if row:
            name, members_str, admin_str, avatar, description = row
            members = members_str.split(',')
            admin_list = [a.strip() for a in (admin_str or '').split(',') if a.strip()]
            if not admin_list and members: admin_list = [members[0]]
            
            if requester in admin_list and target_user in members:
                if action == 'promote' and target_user not in admin_list:
                    admin_list.append(target_user)
                elif action == 'demote' and target_user in admin_list:
                    if len(admin_list) > 1:
                        admin_list.remove(target_user)
                
                new_admin_str = ",".join(admin_list)
                c.execute("UPDATE custom_groups SET admin=? WHERE id=?", (new_admin_str, group_id))
                conn.commit()
                
                updated_data = {
                    'id': group_id_str,
                    'name': name,
                    'avatar': avatar or '/static/WS.jpg',
                    'description': description or 'Group Community',
                    'admin': new_admin_str,
                    'members': members
                }
                
                for member in members:
                    if member in online_users:
                        emit('group_profile_updated', updated_data, room=online_users[member])

@socketio.on('start_group_call')
def handle_start_group_call(data):
    group_id_str = data.get('group_id')
    if not group_id_str: return
    group_id = group_id_str.replace("GROUP_", "")
    caller = data.get('caller')
    is_video = data.get('isVideo', True)
    group_name = data.get('groupName', 'Group Call')
    
    with sqlite3.connect('chat.db', timeout=10) as conn:
        c = conn.cursor()
        c.execute("SELECT members FROM custom_groups WHERE id=?", (group_id,))
        row = c.fetchone()
        if row:
            members = row[0].split(',')
            for member in members:
                if member != caller and member in online_users:
                    emit('group_call_incoming', {
                        'group_id': group_id_str,
                        'group_name': group_name,
                        'caller': caller,
                        'isVideo': is_video
                    }, room=online_users[member])

@socketio.on('group_call_signal')
def handle_group_call_signal(data):
    target = data.get('target')
    if target and target in online_users:
        emit('group_call_signal', data, room=online_users[target])

@socketio.on('leave_group_call')
def handle_leave_group_call(data):
    group_id_str = data.get('group_id')
    user = data.get('user')
    if not group_id_str: return
    group_id = group_id_str.replace("GROUP_", "")
    
    with sqlite3.connect('chat.db', timeout=10) as conn:
        c = conn.cursor()
        c.execute("SELECT members FROM custom_groups WHERE id=?", (group_id,))
        row = c.fetchone()
        if row:
            members = row[0].split(',')
            for member in members:
                if member != user and member in online_users:
                    emit('group_call_user_left', {'user': user, 'group_id': group_id_str}, room=online_users[member])

@socketio.on('disconnect')
def handle_disconnect():
    users_to_remove = [user for user, sid in online_users.items() if sid == request.sid]
    for user in users_to_remove:
        del online_users[user]
    emit('update_users', {'online': list(online_users.keys())}, broadcast=True)

@socketio.on('send_message')
def handle_message(data):
    sender = data.get('user')
    recipient = data.get('recipient') or "" 
    message = data.get('message')

    with sqlite3.connect('chat.db', timeout=10) as conn:
        c = conn.cursor()
        if recipient and not recipient.startswith("GROUP_"):
            c.execute("SELECT 1 FROM blocked_users WHERE blocker=? AND blocked=?", (recipient, sender))
            if c.fetchone(): return 

        c.execute("INSERT INTO messages (sender, recipient, message, is_read, reactions) VALUES (?, ?, ?, 0, '{}')", (sender, recipient, message))
        msg_id = c.lastrowid 
        conn.commit()
        data['id'] = msg_id 
        data['is_read'] = 0
        data['reactions'] = {}

        if recipient.startswith("GROUP_"):
            group_id = recipient.split("_")[1]
            c.execute("SELECT members FROM custom_groups WHERE id=?", (group_id,))
            res = c.fetchone()
            if res:
                members = res[0].split(',')
                for member in members:
                    if member in online_users:
                        emit('receive_message', data, room=online_users[member])
        elif recipient:
            if recipient in online_users:
                emit('receive_message', data, room=online_users[recipient])
            emit('receive_message', data, room=request.sid)
        elif not recipient:
            emit('receive_message', data, broadcast=True)

@socketio.on('delete_message')
def handle_delete(msg_id):
    with sqlite3.connect('chat.db', timeout=10) as conn:
        c = conn.cursor()
        c.execute("DELETE FROM messages WHERE id=?", (msg_id,))
        conn.commit()
    emit('message_deleted', msg_id, broadcast=True)

@socketio.on('typing')
def handle_typing(data):
    sender = data.get('sender')
    recipient = data.get('recipient') or ""
    if recipient.startswith("GROUP_"):
        group_id = recipient.split("_")[1]
        with sqlite3.connect('chat.db', timeout=10) as conn:
            c = conn.cursor()
            c.execute("SELECT members FROM custom_groups WHERE id=?", (group_id,))
            res = c.fetchone()
            if res:
                members = res[0].split(',')
                for member in members:
                    if member in online_users and member != sender:
                        emit('typing', data, room=online_users[member])
    elif recipient in online_users:
        emit('typing', data, room=online_users[recipient])

# ==========================================
# STATUS (24 HOUR STORIES) ROUTES
# ==========================================
@socketio.on('publish_status')
def handle_publish_status(data):
    username = data.get('username')
    media_url = data.get('media_url') or ''
    caption = data.get('caption') or ''
    bg_style = data.get('bg_style') or 'gradient-1'
    font_style = data.get('font_style') or 'sans-serif'
    music_url = data.get('music_url') or ''
    
    with sqlite3.connect('chat.db', timeout=10) as conn:
        c = conn.cursor()
        c.execute("INSERT INTO statuses (username, media_url, caption, bg_style, font_style, music_url, viewers, reactions) VALUES (?, ?, ?, ?, ?, ?, '', '{}')", 
                  (username, media_url, caption, bg_style, font_style, music_url))
        conn.commit()
    emit('status_updated', broadcast=True)

@socketio.on('request_statuses')
def handle_request_statuses():
    with sqlite3.connect('chat.db', timeout=10) as conn:
        c = conn.cursor()
        c.execute("SELECT id, username, media_url, caption, timestamp, viewers, bg_style, font_style, music_url, reactions FROM statuses WHERE timestamp >= datetime('now', '-24 hours') ORDER BY timestamp ASC")
        statuses = [{
            'id': row[0], 
            'username': row[1], 
            'media_url': row[2], 
            'caption': row[3], 
            'time': row[4], 
            'viewers': row[5],
            'bg_style': row[6] or 'gradient-1',
            'font_style': row[7] or 'sans-serif',
            'music_url': row[8] or '',
            'reactions': json.loads(row[9]) if row[9] else {}
        } for row in c.fetchall()]
    emit('load_statuses', statuses, room=request.sid)

@socketio.on('react_status')
def handle_react_status(data):
    status_id = data.get('status_id')
    username = data.get('username')
    reaction = data.get('reaction')
    
    with sqlite3.connect('chat.db', timeout=10) as conn:
        c = conn.cursor()
        c.execute("SELECT reactions, username FROM statuses WHERE id=?", (status_id,))
        row = c.fetchone()
        if row:
            try: reactions_dict = json.loads(row[0]) if row[0] else {}
            except json.JSONDecodeError: reactions_dict = {}
            
            reactions_dict[username] = reaction
            c.execute("UPDATE statuses SET reactions=? WHERE id=?", (json.dumps(reactions_dict), status_id))
            conn.commit()
            
            status_owner = row[1]
            if status_owner in online_users and status_owner != username:
                emit('status_reaction_received', {
                    'status_id': status_id,
                    'reactor': username,
                    'reaction': reaction
                }, room=online_users[status_owner])
    emit('status_updated', broadcast=True)

@socketio.on('view_status')
def handle_view_status(data):
    status_id = data.get('status_id')
    viewer = data.get('username')
    with sqlite3.connect('chat.db', timeout=10) as conn:
        c = conn.cursor()
        c.execute("SELECT viewers FROM statuses WHERE id=?", (status_id,))
        row = c.fetchone()
        if row:
            viewers = row[0].split(',') if row[0] else []
            if viewer not in viewers:
                viewers.append(viewer)
                c.execute("UPDATE statuses SET viewers=? WHERE id=?", (",".join(viewers), status_id))
                conn.commit()

@socketio.on('delete_status')
def handle_delete_status(status_id):
    with sqlite3.connect('chat.db', timeout=10) as conn:
        c = conn.cursor()
        c.execute("DELETE FROM statuses WHERE id=?", (status_id,))
        conn.commit()
    emit('status_updated', broadcast=True)

@socketio.on('edit_status')
def handle_edit_status(data):
    status_id = data.get('status_id')
    new_caption = data.get('caption')
    with sqlite3.connect('chat.db', timeout=10) as conn:
        c = conn.cursor()
        c.execute("UPDATE statuses SET caption=? WHERE id=?", (new_caption, status_id))
        conn.commit()
    emit('status_updated', broadcast=True)

# ==========================================
# REELS ROUTES
# ==========================================
@socketio.on('publish_reel')
def handle_publish_reel(data):
    username = data.get('username')
    video_url = data.get('video_url')
    caption = data.get('caption')
    audio_title = data.get('audio_title') or f"Original Audio - @{username}"
    
    with sqlite3.connect('chat.db', timeout=10) as conn:
        c = conn.cursor()
        c.execute("INSERT INTO reels (username, video_url, caption, audio_title, views, likes, liked_by, comments_count) VALUES (?, ?, ?, ?, 0, 0, '', 0)", 
                  (username, video_url, caption, audio_title))
        reel_id = c.lastrowid
        conn.commit()
    emit('new_reel', {'id': reel_id, 'username': username, 'video_url': video_url, 'caption': caption, 'audio_title': audio_title, 'views': 0, 'likes': 0, 'liked_by': '', 'comments_count': 0}, broadcast=True)

@socketio.on('request_reels')
def handle_request_reels():
    with sqlite3.connect('chat.db', timeout=10) as conn:
        c = conn.cursor()
        c.execute("SELECT id, username, video_url, caption, views, likes, liked_by, audio_title, comments_count FROM reels ORDER BY RANDOM()")
        reels = [{'id': row[0], 'username': row[1], 'video_url': row[2], 'caption': row[3], 'views': row[4], 'likes': row[5], 'liked_by': row[6], 'audio_title': row[7] or 'Original Audio', 'comments_count': row[8] or 0} for row in c.fetchall()]
    emit('load_reels', reels, room=request.sid)

@socketio.on('increment_view')
def handle_increment_view(reel_id):
    with sqlite3.connect('chat.db', timeout=10) as conn:
        c = conn.cursor()
        c.execute("UPDATE reels SET views = views + 1 WHERE id = ?", (reel_id,))
        conn.commit()

@socketio.on('like_reel')
def handle_like_reel(data):
    reel_id = data.get('id')
    username = data.get('username')
    with sqlite3.connect('chat.db', timeout=10) as conn:
        c = conn.cursor()
        c.execute("SELECT liked_by FROM reels WHERE id=?", (reel_id,))
        row = c.fetchone()
        if row:
            liked_by = row[0].split(',') if row[0] else []
            if username in liked_by:
                liked_by.remove(username)
            else:
                liked_by.append(username)
            
            new_liked_by = ",".join(liked_by)
            new_likes = len(liked_by)
            c.execute("UPDATE reels SET likes=?, liked_by=? WHERE id=?", (new_likes, new_liked_by, reel_id))
            conn.commit()
            emit('reel_liked', {'id': reel_id, 'likes': new_likes, 'liked_by': new_liked_by}, broadcast=True)

@socketio.on('add_reel_comment')
def handle_add_reel_comment(data):
    reel_id = data.get('reel_id')
    username = data.get('username')
    comment = data.get('comment')
    if not reel_id or not username or not comment: return
    
    with sqlite3.connect('chat.db', timeout=10) as conn:
        c = conn.cursor()
        c.execute("INSERT INTO reel_comments (reel_id, username, comment) VALUES (?, ?, ?)", (reel_id, username, comment))
        c.execute("UPDATE reels SET comments_count = comments_count + 1 WHERE id = ?", (reel_id,))
        c.execute("SELECT comments_count FROM reels WHERE id = ?", (reel_id,))
        row = c.fetchone()
        comments_count = row[0] if row else 1
        conn.commit()
    
    emit('reel_comment_added', {'reel_id': reel_id, 'username': username, 'comment': comment, 'comments_count': comments_count}, broadcast=True)

@socketio.on('get_reel_comments')
def handle_get_reel_comments(reel_id):
    with sqlite3.connect('chat.db', timeout=10) as conn:
        c = conn.cursor()
        c.execute("SELECT id, username, comment, timestamp FROM reel_comments WHERE reel_id = ? ORDER BY id ASC", (reel_id,))
        comments = [{'id': row[0], 'username': row[1], 'comment': row[2], 'time': row[3]} for row in c.fetchall()]
    emit('load_reel_comments', {'reel_id': reel_id, 'comments': comments}, room=request.sid)

@socketio.on('request_my_reels')
def handle_request_my_reels(username):
    with sqlite3.connect('chat.db', timeout=10) as conn:
        c = conn.cursor()
        c.execute("SELECT id, video_url, caption, views, likes, liked_by FROM reels WHERE username = ? ORDER BY id DESC", (username,))
        my_reels = [{'id': row[0], 'video_url': row[1], 'caption': row[2], 'views': row[3], 'likes': row[4], 'liked_by': row[5]} for row in c.fetchall()]
    emit('load_my_reels', my_reels, room=request.sid)

@socketio.on('delete_reel')
def handle_delete_reel(data):
    reel_id = data.get('id')
    username = data.get('username')
    
    if not reel_id or not username: return
    
    is_admin_user = check_is_admin(username)
    
    with sqlite3.connect('chat.db', timeout=10) as conn:
        c = conn.cursor()
        
        # Fetch author before deletion for admin notice
        c.execute("SELECT username, caption FROM reels WHERE id=?", (reel_id,))
        reel_row = c.fetchone()
        reel_author = reel_row[0] if reel_row else None
        reel_caption = reel_row[1] if reel_row else ''
        
        if is_admin_user:
            c.execute("DELETE FROM reels WHERE id=?", (reel_id,))
        else:
            c.execute("DELETE FROM reels WHERE id=? AND username=?", (reel_id, username))
            
        c.execute("DELETE FROM reel_comments WHERE reel_id=?", (reel_id,))
        conn.commit()
        
        c.execute("SELECT id, username, video_url, caption, views, likes FROM reels ORDER BY id DESC")
        reels = [{'id': r[0], 'username': r[1], 'video_url': r[2], 'caption': r[3], 'views': r[4], 'likes': r[5]} for r in c.fetchall()]

        # Automatic Notice to Author when Reel is removed by Admin
        if is_admin_user and reel_author:
            notice_text = f"⚠️ OFFICIAL REEL REMOVAL NOTICE: Your Reel video (ID #{reel_id} - '{reel_caption or 'No caption'}') was removed by Master Admin due to policy violations."
            
            notice_payload = {
                'title': '⚠️ REEL REMOVED BY ADMIN',
                'message': notice_text,
                'sender': username,
                'timestamp': datetime.datetime.now().strftime('%H:%M')
            }
            if reel_author in online_users:
                socketio.emit('official_admin_warning_notice', notice_payload, room=online_users[reel_author])
                
            card_html = f'''<div class="system-warning-notice-card" style="background: rgba(239, 68, 68, 0.15); border: 2px solid #ef4444; border-radius: 20px; padding: 16px; margin: 10px 0; box-shadow: 0 10px 30px rgba(239,68,68,0.4);">
                <div style="font-weight: 900; color: #ef4444; font-size: 14px; margin-bottom: 6px; display: flex; align-items: center; gap: 8px;">
                    <i class="fa-solid fa-triangle-exclamation fa-bounce"></i> REEL REMOVED BY ADMIN
                </div>
                <div style="color: #fff; font-size: 14px; font-weight: 600; line-height: 1.5;">{notice_text}</div>
                <div style="font-size: 11px; color: rgba(255,255,255,0.6); margin-top: 8px; text-align: right;">Issued by Master Admin @{username}</div>
            </div>'''
            c.execute("INSERT INTO messages (sender, recipient, message) VALUES ('MasterAdmin', ?, ?)", (reel_author, card_html))
            conn.commit()
        
    emit('reel_deleted', reel_id, broadcast=True)
    socketio.emit('load_admin_reels', reels)
    handle_request_my_reels(username)

# ==========================================
# CALL LOGIC & WEBRTC ROUTES
# ==========================================
@socketio.on('request_call_history')
def handle_call_history(username):
    with sqlite3.connect('chat.db', timeout=10) as conn:
        c = conn.cursor()
        c.execute("UPDATE calls SET is_read = 1 WHERE receiver = ? AND status = 'Missed'", (username,))
        conn.commit()
        
        c.execute("SELECT caller, receiver, call_type, status, timestamp FROM calls WHERE caller = ? OR receiver = ? ORDER BY id DESC LIMIT 50", (username, username))
        calls = [{'caller': row[0], 'receiver': row[1], 'type': row[2], 'status': row[3], 'time': row[4]} for row in c.fetchall()]
    emit('load_call_history', calls, room=request.sid)
    emit('unread_calls_count', 0, room=request.sid) 

@socketio.on('webrtc_offer')
def handle_offer(data):
    caller = data['sender']
    receiver = data['recipient']
    call_type = 'Video' if data.get('isVideo') else 'Audio'
    
    with sqlite3.connect('chat.db', timeout=10) as conn:
        c = conn.cursor()
        c.execute("INSERT INTO calls (caller, receiver, call_type, status) VALUES (?, ?, ?, 'Missed')", (caller, receiver, call_type))
        call_id = c.lastrowid
        conn.commit()
    
    active_calls[caller] = call_id
    data['call_id'] = call_id

    if receiver in online_users: 
        emit('webrtc_offer', data, room=online_users[receiver])

@socketio.on('webrtc_answer')
def handle_answer(data):
    caller = data['recipient']
    call_id = data.get('call_id')
    if not call_id and caller in active_calls:
        call_id = active_calls[caller]

    if call_id:
        with sqlite3.connect('chat.db', timeout=10) as conn:
            c = conn.cursor()
            c.execute("UPDATE calls SET status = 'Answered', is_read = 1 WHERE id = ?", (call_id,))
            conn.commit()

    if caller in online_users: 
        emit('webrtc_answer', data, room=online_users[caller])

@socketio.on('reject_call')
def handle_reject_call(data):
    caller = data['sender']
    call_id = data.get('call_id')
    if not call_id and caller in active_calls:
        call_id = active_calls[caller]
        
    if call_id:
        with sqlite3.connect('chat.db', timeout=10) as conn:
            c = conn.cursor()
            c.execute("UPDATE calls SET status = 'Declined', is_read = 1 WHERE id = ?", (call_id,))
            conn.commit()
            
    if caller in online_users: 
        emit('call_rejected', data, room=online_users[caller])

@socketio.on('webrtc_ice_candidate')
def handle_ice_candidate(data):
    if data['recipient'] in online_users: 
        emit('webrtc_ice_candidate', data, room=online_users[data['recipient']])

@socketio.on('end_call')
def handle_end_call(data):
    if data['recipient'] in online_users: 
        emit('call_ended', data, room=online_users[data['recipient']])
        
        with sqlite3.connect('chat.db', timeout=10) as conn:
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM calls WHERE receiver=? AND status='Missed' AND is_read=0", (data['recipient'],))
            unread = c.fetchone()[0]
        emit('unread_calls_count', unread, room=online_users[data['recipient']])

# ==========================================
# FRIEND REQUEST ROUTES
# ==========================================
@socketio.on('send_friend_request')
def handle_send_friend_request(data):
    sender = data.get('sender')
    receiver = data.get('receiver')
    with sqlite3.connect('chat.db', timeout=10) as conn:
        c = conn.cursor()
        c.execute("SELECT 1 FROM friendships WHERE (sender=? AND receiver=?) OR (sender=? AND receiver=?)", (sender, receiver, receiver, sender))
        if not c.fetchone():
            c.execute("INSERT INTO friendships (sender, receiver, status) VALUES (?, ?, 'pending')", (sender, receiver))
            conn.commit()
    
    update = {'sender': sender, 'receiver': receiver, 'status': 'pending'}
    if sender in online_users: emit('friendship_update', update, room=online_users[sender])
    if receiver in online_users: emit('friendship_update', update, room=online_users[receiver])

@socketio.on('accept_friend_request')
def handle_accept_friend_request(data):
    sender = data.get('sender')
    receiver = data.get('receiver')
    with sqlite3.connect('chat.db', timeout=10) as conn:
        c = conn.cursor()
        c.execute("UPDATE friendships SET status='accepted' WHERE sender=? AND receiver=?", (sender, receiver))
        conn.commit()
        
    update = {'sender': sender, 'receiver': receiver, 'status': 'accepted'}
    if sender in online_users: emit('friendship_update', update, room=online_users[sender])
    if receiver in online_users: emit('friendship_update', update, room=online_users[receiver])

@socketio.on('reject_friend_request')
def handle_reject_friend_request(data):
    sender = data.get('sender')
    receiver = data.get('receiver')
    with sqlite3.connect('chat.db', timeout=10) as conn:
        c = conn.cursor()
        c.execute("DELETE FROM friendships WHERE sender=? AND receiver=?", (sender, receiver))
        conn.commit()
        
    update = {'sender': sender, 'receiver': receiver, 'status': 'rejected'}
    if sender in online_users: emit('friendship_update', update, room=online_users[sender])
    if receiver in online_users: emit('friendship_update', update, room=online_users[receiver])

# ==========================================
# SCHEDULED / TIMER MESSAGES ROUTES & SCHEDULER
# ==========================================
def process_scheduled_messages():
    while True:
        socketio.sleep(2)
        try:
            with sqlite3.connect('chat.db', timeout=10) as conn:
                c = conn.cursor()
                now_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                c.execute("SELECT id, sender, recipient, message FROM scheduled_messages WHERE send_at <= ? AND status='pending'", (now_str,))
                due_messages = c.fetchall()
                
                for msg_id, sender, recipient, message in due_messages:
                    c.execute("INSERT INTO messages (sender, recipient, message) VALUES (?, ?, ?)", (sender, recipient, message))
                    message_id = c.lastrowid
                    c.execute("UPDATE scheduled_messages SET status='sent' WHERE id=?", (msg_id,))
                    conn.commit()
                    
                    msg_payload = {
                        'id': message_id,
                        'user': sender,
                        'recipient': recipient,
                        'message': message,
                        'time': datetime.datetime.now().strftime('%H:%M'),
                        'is_read': 0,
                        'reactions': '{}'
                    }
                    
                    if recipient.startswith("GROUP_"):
                        try:
                            group_id = int(recipient.replace("GROUP_", ""))
                            c.execute("SELECT members FROM custom_groups WHERE id=?", (group_id,))
                            row = c.fetchone()
                            if row:
                                members = row[0].split(',') if row[0] else []
                                for m in members:
                                    if m in online_users:
                                        socketio.emit('new_message', msg_payload, room=online_users[m])
                        except Exception as e:
                            pass
                    else:
                        if recipient in online_users:
                            socketio.emit('new_message', msg_payload, room=online_users[recipient])
                        if sender in online_users:
                            socketio.emit('new_message', msg_payload, room=online_users[sender])
        except Exception as e:
            print("Scheduler error:", e)

socketio.start_background_task(process_scheduled_messages)

@socketio.on('schedule_message')
def handle_schedule_message(data):
    sender = data.get('sender')
    recipient = data.get('recipient')
    message = data.get('message')
    send_at = data.get('send_at') # YYYY-MM-DD HH:MM:SS format
    
    if not sender or not recipient or not message or not send_at:
        return
        
    with sqlite3.connect('chat.db', timeout=10) as conn:
        c = conn.cursor()
        c.execute("INSERT INTO scheduled_messages (sender, recipient, message, send_at, status) VALUES (?, ?, ?, ?, 'pending')",
                  (sender, recipient, message, send_at))
        conn.commit()
        
    emit('message_scheduled', {'sender': sender, 'recipient': recipient, 'send_at': send_at}, room=request.sid)

@socketio.on('get_scheduled_messages')
def handle_get_scheduled_messages(data):
    sender = data.get('sender')
    with sqlite3.connect('chat.db', timeout=10) as conn:
        c = conn.cursor()
        c.execute("SELECT id, recipient, message, send_at FROM scheduled_messages WHERE sender=? AND status='pending' ORDER BY send_at ASC", (sender,))
        scheduled = [{'id': row[0], 'recipient': row[1], 'message': row[2], 'send_at': row[3]} for row in c.fetchall()]
    emit('load_scheduled_messages', scheduled, room=request.sid)

@socketio.on('cancel_scheduled_message')
def handle_cancel_scheduled_message(data):
    msg_id = data.get('id')
    sender = data.get('sender')
    with sqlite3.connect('chat.db', timeout=10) as conn:
        c = conn.cursor()
        c.execute("DELETE FROM scheduled_messages WHERE id=? AND sender=?", (msg_id, sender))
        conn.commit()
    emit('scheduled_message_cancelled', msg_id, room=request.sid)

@socketio.on('update_profile_settings')
def handle_update_profile_settings(data):
    username = data.get('username')
    avatar = data.get('avatar')
    bio = data.get('bio')
    is_private = 1 if data.get('is_private') else 0
    
    with sqlite3.connect('chat.db', timeout=10) as conn:
        c = conn.cursor()
        if avatar and bio:
            c.execute("UPDATE users SET avatar=?, bio=?, is_private=? WHERE username=?", (avatar, bio, is_private, username))
        elif avatar:
            c.execute("UPDATE users SET avatar=?, is_private=? WHERE username=?", (avatar, is_private, username))
        elif bio:
            c.execute("UPDATE users SET bio=?, is_private=? WHERE username=?", (bio, is_private, username))
        else:
            c.execute("UPDATE users SET is_private=? WHERE username=?", (is_private, username))
        conn.commit()
        
        c.execute("SELECT username, avatar, bio, is_private, win_streak FROM users")
        profiles = {row[0]: {'avatar': row[1] or '/static/WS.jpg', 'bio': row[2] or 'Available', 'is_private': row[3] or 0, 'win_streak': row[4] or 0} for row in c.fetchall()}
        
    emit('profile_updated', {'username': username, 'is_private': is_private, 'profiles': profiles}, broadcast=True)

# ==========================================
# MULTIPLAYER GAMING & WIN STREAK SYSTEM
# ==========================================
active_games = {}

@socketio.on('create_game_challenge')
def handle_create_game_challenge(data):
    game_id = f"GAME_{int(time.time()*1000)}"
    challenger = data.get('challenger')
    target = data.get('target')
    game_type = data.get('game_type', 'tic_tac_toe')
    recipient = data.get('recipient')
    
    active_games[game_id] = {
        'id': game_id,
        'challenger': challenger,
        'opponent': target,
        'game_type': game_type,
        'status': 'waiting',
        'board': [''] * 9,
        'current_turn': challenger,
        'winner': None
    }
    
    card_html = f'''<div class="shared-reel-video-card" style="width: 100%; max-width: 300px; border-radius: 20px; overflow: hidden; background: rgba(15,15,25,0.95); border: 2px solid #ec4899; box-shadow: 0 12px 35px rgba(236,72,153,0.3); margin: 6px 0;">
        <div style="padding: 12px 14px; display: flex; align-items: center; justify-content: space-between; background: linear-gradient(135deg, rgba(236,72,153,0.4), rgba(139,92,246,0.4)); border-bottom: 1px solid rgba(255,255,255,0.1);">
            <div style="display: flex; align-items: center; gap: 8px;">
                <i class="fa-solid fa-gamepad" style="color: #ec4899; font-size: 18px;"></i>
                <span style="font-weight: 700; color: #fff; font-size: 14px;">🎮 Game Challenge</span>
            </div>
            <span style="font-size: 10px; font-weight: 700; background: rgba(0,0,0,0.5); padding: 3px 8px; border-radius: 10px; color: #ec4899; border: 1px solid rgba(236,72,153,0.3);">🔥 MULTIPLAYER</span>
        </div>
        <div style="padding: 16px; text-align: left;">
            <div style="font-size: 14px; color: #fff; font-weight: 700; margin-bottom: 4px;">🎯 Tic-Tac-Toe Cyber Match</div>
            <div style="font-size: 12px; color: rgba(255,255,255,0.8); margin-bottom: 14px;">
                <b>@{challenger}</b> challenged <b>{f"@{target}" if target else "Anyone in Lounge"}</b> to a game match!
            </div>
            <button class="send-btn" style="width: 100%; background: linear-gradient(135deg, #ec4899, #8b5cf6); font-weight: 700; font-size: 13px;" onclick="acceptGameChallenge('{game_id}')">
                ⚔️ Accept & Play Match
            </button>
        </div>
    </div>'''
    
    with sqlite3.connect('chat.db', timeout=10) as conn:
        c = conn.cursor()
        c.execute("INSERT INTO messages (sender, recipient, message) VALUES (?, ?, ?)", (challenger, recipient, card_html))
        conn.commit()
        msg_id = c.lastrowid
        
    emit('receive_message', {
        'id': msg_id,
        'user': challenger,
        'recipient': recipient,
        'message': card_html,
        'is_read': 0,
        'reactions': {}
    }, broadcast=True)

@socketio.on('accept_game_challenge')
def handle_accept_game_challenge(data):
    game_id = data.get('game_id')
    player = data.get('player')
    
    if game_id in active_games:
        game = active_games[game_id]
        if game['status'] == 'waiting' and player != game['challenger']:
            game['opponent'] = player
            game['status'] = 'playing'
            emit('game_started', game, broadcast=True)

@socketio.on('make_game_move')
def handle_make_game_move(data):
    game_id = data.get('game_id')
    player = data.get('player')
    index = data.get('index')
    
    if game_id in active_games:
        game = active_games[game_id]
        if game['status'] == 'playing' and game['current_turn'] == player:
            if 0 <= index <= 8 and game['board'][index] == '':
                symbol = 'X' if player == game['challenger'] else 'O'
                game['board'][index] = symbol
                
                b = game['board']
                wins = [(0,1,2),(3,4,5),(6,7,8),(0,3,6),(1,4,7),(2,5,8),(0,4,8),(2,4,6)]
                winner = None
                winning_indices = []
                for w in wins:
                    if b[w[0]] != '' and b[w[0]] == b[w[1]] == b[w[2]]:
                        winner = player
                        winning_indices = list(w)
                        break
                        
                if winner:
                    game['status'] = 'finished'
                    game['winner'] = winner
                    game['winning_indices'] = winning_indices
                    loser = game['opponent'] if winner == game['challenger'] else game['challenger']
                    
                    with sqlite3.connect('chat.db', timeout=10) as conn:
                        c = conn.cursor()
                        c.execute("UPDATE users SET win_streak = win_streak + 1 WHERE username=?", (winner,))
                        c.execute("UPDATE users SET win_streak = 0 WHERE username=?", (loser,))
                        conn.commit()
                        
                        c.execute("SELECT username, avatar, bio, is_private, win_streak FROM users")
                        profiles = {row[0]: {'avatar': row[1] or '/static/WS.jpg', 'bio': row[2] or 'Available', 'is_private': row[3] or 0, 'win_streak': row[4] or 0} for row in c.fetchall()}
                        
                    emit('game_finished', {'game': game, 'winner': winner, 'loser': loser, 'profiles': profiles}, broadcast=True)
                elif '' not in b:
                    game['status'] = 'draw'
                    emit('game_finished', {'game': game, 'winner': 'draw'}, broadcast=True)
                else:
                    game['current_turn'] = game['opponent'] if player == game['challenger'] else game['challenger']
                    emit('game_move_made', game, broadcast=True)

# ==========================================
# MASTER ADMIN CONTROL CENTER SOCKETIO API
# ==========================================
def check_is_admin(username):
    if not username: return False
    if username.strip().lower() == "x13": return True
    with sqlite3.connect('chat.db', timeout=10) as conn:
        c = conn.cursor()
        c.execute("SELECT is_admin FROM users WHERE username=?", (username,))
        row = c.fetchone()
        return bool(row and row[0])

@socketio.on('request_admin_stats')
def handle_request_admin_stats(data):
    admin_user = data.get('admin_user')
    if not check_is_admin(admin_user): return
    
    with sqlite3.connect('chat.db', timeout=10) as conn:
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM users")
        total_users = c.fetchone()[0]
        
        c.execute("SELECT COUNT(*) FROM users WHERE is_frozen = 1")
        frozen_users = c.fetchone()[0]

        c.execute("SELECT COUNT(*) FROM reels")
        total_reels = c.fetchone()[0]

        c.execute("SELECT COUNT(*) FROM messages")
        total_messages = c.fetchone()[0]

        c.execute("SELECT COUNT(*) FROM reports WHERE status = 'pending'")
        pending_reports = c.fetchone()[0]
        
    stats = {
        'total_users': total_users,
        'online_users': len(online_users),
        'frozen_users': frozen_users,
        'total_reels': total_reels,
        'total_messages': total_messages,
        'pending_reports': pending_reports
    }
    emit('load_admin_stats', stats, room=request.sid)

@socketio.on('admin_get_users')
def handle_admin_get_users(data):
    admin_user = data.get('admin_user')
    if not check_is_admin(admin_user): return
    
    with sqlite3.connect('chat.db', timeout=10) as conn:
        c = conn.cursor()
        c.execute("SELECT id, username, avatar, bio, is_admin, is_frozen, win_streak FROM users ORDER BY id DESC")
        users = [{'id': r[0], 'username': r[1], 'avatar': r[2] or '/static/WS.jpg', 'bio': r[3] or '', 'is_admin': r[4] or 0, 'is_frozen': r[5] or 0, 'win_streak': r[6] or 0, 'is_online': r[1] in online_users} for r in c.fetchall()]
    emit('load_admin_users', users, room=request.sid)

@socketio.on('admin_toggle_freeze')
def handle_admin_toggle_freeze(data):
    admin_user = data.get('admin_user')
    target_user = data.get('target_user')
    if not check_is_admin(admin_user) or not target_user: return
    
    with sqlite3.connect('chat.db', timeout=10) as conn:
        c = conn.cursor()
        c.execute("SELECT is_frozen FROM users WHERE username=?", (target_user,))
        row = c.fetchone()
        if row:
            new_frozen = 0 if row[0] else 1
            c.execute("UPDATE users SET is_frozen=? WHERE username=?", (new_frozen, target_user))
            conn.commit()
            
            if new_frozen and target_user in online_users:
                notice_payload = {
                    'title': '⛔ ACCOUNT FROZEN BY ADMIN',
                    'message': f'Your account (@{target_user}) has been frozen by System Admin due to community terms violation.',
                    'sender': admin_user,
                    'timestamp': datetime.datetime.now().strftime('%H:%M')
                }
                emit('official_admin_warning_notice', notice_payload, room=online_users[target_user])
                emit('account_frozen_notice', {'user': target_user}, room=online_users[target_user])
                
            emit('admin_user_updated', {'username': target_user, 'is_frozen': new_frozen}, broadcast=True)

@socketio.on('admin_delete_user')
def handle_admin_delete_user(data):
    admin_user = data.get('admin_user')
    target_user = data.get('target_user')
    if not check_is_admin(admin_user) or not target_user: return
    
    if target_user in online_users:
        notice_payload = {
            'title': '⛔ ACCOUNT TERMINATION NOTICE',
            'message': f'Your account (@{target_user}) and all associated content have been permanently deleted by System Administrator.',
            'sender': admin_user,
            'timestamp': datetime.datetime.now().strftime('%H:%M')
        }
        emit('official_admin_warning_notice', notice_payload, room=online_users[target_user])
        emit('account_deleted_notice', {'user': target_user}, room=online_users[target_user])

    with sqlite3.connect('chat.db', timeout=10) as conn:
        c = conn.cursor()
        c.execute("DELETE FROM users WHERE username=?", (target_user,))
        c.execute("DELETE FROM reels WHERE username=?", (target_user,))
        c.execute("DELETE FROM statuses WHERE username=?", (target_user,))
        c.execute("DELETE FROM messages WHERE sender=? OR recipient=?", (target_user, target_user))
        conn.commit()
        
    emit('admin_user_deleted', {'username': target_user}, broadcast=True)

@socketio.on('admin_toggle_role')
def handle_admin_toggle_role(data):
    admin_user = data.get('admin_user')
    target_user = data.get('target_user')
    if not check_is_admin(admin_user) or not target_user: return
    
    with sqlite3.connect('chat.db', timeout=10) as conn:
        c = conn.cursor()
        c.execute("SELECT is_admin FROM users WHERE username=?", (target_user,))
        row = c.fetchone()
        if row:
            new_admin = 0 if row[0] else 1
            c.execute("UPDATE users SET is_admin=? WHERE username=?", (new_admin, target_user))
            conn.commit()
            emit('admin_user_updated', {'username': target_user, 'is_admin': new_admin}, broadcast=True)

@socketio.on('admin_get_reels')
def handle_admin_get_reels(data):
    admin_user = data.get('admin_user')
    if not check_is_admin(admin_user): return
    
    with sqlite3.connect('chat.db', timeout=10) as conn:
        c = conn.cursor()
        c.execute("SELECT id, username, video_url, caption, views, likes FROM reels ORDER BY id DESC")
        reels = [{'id': r[0], 'username': r[1], 'video_url': r[2], 'caption': r[3], 'views': r[4], 'likes': r[5]} for r in c.fetchall()]
    emit('load_admin_reels', reels, room=request.sid)

@socketio.on('admin_get_reports')
def handle_admin_get_reports(data):
    admin_user = data.get('admin_user')
    if not check_is_admin(admin_user): return
    
    with sqlite3.connect('chat.db', timeout=10) as conn:
        c = conn.cursor()
        c.execute("SELECT id, reporter, target_type, target_id, reason, timestamp, status FROM reports ORDER BY id DESC")
        reports = [{'id': r[0], 'reporter': r[1], 'target_type': r[2], 'target_id': r[3], 'reason': r[4], 'timestamp': r[5], 'status': r[6]} for r in c.fetchall()]
    emit('load_admin_reports', reports, room=request.sid)

@socketio.on('submit_user_report')
def handle_submit_user_report(data):
    reporter = data.get('reporter')
    target_type = data.get('target_type') # 'User', 'Reel', 'Message'
    target_id = data.get('target_id')
    reason = data.get('reason')
    
    if not reporter or not target_type or not target_id: return
    
    with sqlite3.connect('chat.db', timeout=10) as conn:
        c = conn.cursor()
        c.execute("INSERT INTO reports (reporter, target_type, target_id, reason) VALUES (?, ?, ?, ?)",
                  (reporter, target_type, target_id, reason))
        conn.commit()
        
        c.execute("SELECT id, reporter, target_type, target_id, reason, timestamp, status FROM reports ORDER BY id DESC")
        reports = [{'id': r[0], 'reporter': r[1], 'target_type': r[2], 'target_id': r[3], 'reason': r[4], 'timestamp': r[5], 'status': r[6]} for r in c.fetchall()]
        
    emit('report_submitted_ack', {'status': 'ok'}, room=request.sid)
    socketio.emit('load_admin_reports', reports)

@socketio.on('admin_resolve_report')
def handle_admin_resolve_report(data):
    admin_user = data.get('admin_user')
    report_id = data.get('report_id')
    if not check_is_admin(admin_user) or not report_id: return
    
    with sqlite3.connect('chat.db', timeout=10) as conn:
        c = conn.cursor()
        c.execute("UPDATE reports SET status='resolved' WHERE id=?", (report_id,))
        conn.commit()
        
        c.execute("SELECT id, reporter, target_type, target_id, reason, timestamp, status FROM reports ORDER BY id DESC")
        reports = [{'id': r[0], 'reporter': r[1], 'target_type': r[2], 'target_id': r[3], 'reason': r[4], 'timestamp': r[5], 'status': r[6]} for r in c.fetchall()]
        
    socketio.emit('load_admin_reports', reports)

@socketio.on('admin_delete_report')
def handle_admin_delete_report(data):
    admin_user = data.get('admin_user')
    report_id = data.get('report_id')
    if not check_is_admin(admin_user) or not report_id: return
    
    with sqlite3.connect('chat.db', timeout=10) as conn:
        c = conn.cursor()
        c.execute("DELETE FROM reports WHERE id=?", (report_id,))
        conn.commit()
        
        c.execute("SELECT id, reporter, target_type, target_id, reason, timestamp, status FROM reports ORDER BY id DESC")
        reports = [{'id': r[0], 'reporter': r[1], 'target_type': r[2], 'target_id': r[3], 'reason': r[4], 'timestamp': r[5], 'status': r[6]} for r in c.fetchall()]
        
    socketio.emit('load_admin_reports', reports)

@socketio.on('admin_send_notice')
def handle_admin_send_notice(data):
    admin_user = data.get('admin_user')
    target_user = data.get('target_user')
    notice_text = data.get('notice_text', '').strip()
    
    if not check_is_admin(admin_user) or not target_user or not notice_text: return
    
    notice_payload = {
        'title': '⚠️ OFFICIAL ADMIN WARNING NOTICE',
        'message': notice_text,
        'sender': admin_user,
        'timestamp': datetime.datetime.now().strftime('%H:%M')
    }
    
    # 1. Send live warning modal & toast to target user's socket room if online
    if target_user in online_users:
        socketio.emit('official_admin_warning_notice', notice_payload, room=online_users[target_user])
        
    # 2. Also send as an official warning chat card in target user's private messages
    with sqlite3.connect('chat.db', timeout=10) as conn:
        c = conn.cursor()
        card_html = f'''<div class="system-warning-notice-card" style="background: rgba(239, 68, 68, 0.15); border: 2px solid #ef4444; border-radius: 20px; padding: 16px; margin: 10px 0; box-shadow: 0 10px 30px rgba(239,68,68,0.4);">
            <div style="font-weight: 900; color: #ef4444; font-size: 14px; margin-bottom: 6px; display: flex; align-items: center; gap: 8px;">
                <i class="fa-solid fa-triangle-exclamation fa-bounce"></i> OFFICIAL ADMIN WARNING NOTICE
            </div>
            <div style="color: #fff; font-size: 14px; font-weight: 600; line-height: 1.5;">{notice_text}</div>
            <div style="font-size: 11px; color: rgba(255,255,255,0.6); margin-top: 8px; text-align: right;">Issued by Master Admin @{admin_user}</div>
        </div>'''
        c.execute("INSERT INTO messages (sender, recipient, message) VALUES ('MasterAdmin', ?, ?)", (target_user, card_html))
        conn.commit()
        msg_id = c.lastrowid
        
    if target_user in online_users:
        socketio.emit('receive_message', {
            'id': msg_id,
            'user': 'MasterAdmin',
            'recipient': target_user,
            'message': card_html,
            'is_read': 0,
            'reactions': {}
        }, room=online_users[target_user])

@socketio.on('admin_edit_user_details')
def handle_admin_edit_user_details(data):
    admin_user = data.get('admin_user')
    target_user = data.get('target_user')
    new_bio = data.get('bio')
    new_streak = data.get('win_streak')
    new_password = data.get('password')
    
    if not check_is_admin(admin_user) or not target_user: return
    
    with sqlite3.connect('chat.db', timeout=10) as conn:
        c = conn.cursor()
        if new_bio is not None:
            c.execute("UPDATE users SET bio=? WHERE username=?", (new_bio, target_user))
        if new_streak is not None:
            c.execute("UPDATE users SET win_streak=? WHERE username=?", (int(new_streak), target_user))
        if new_password and new_password.strip():
            hashed_pw = generate_password_hash(new_password.strip())
            c.execute("UPDATE users SET password=? WHERE username=?", (hashed_pw, target_user))
        conn.commit()
        
    emit('admin_user_updated', {'username': target_user}, broadcast=True)

@socketio.on('get_highest_streaks')
def handle_get_highest_streaks():
    with sqlite3.connect('chat.db', timeout=10) as conn:
        c = conn.cursor()
        c.execute("SELECT username, avatar, win_streak, bio FROM users ORDER BY win_streak DESC, id ASC LIMIT 20")
        top_users = [{'username': r[0], 'avatar': r[1] or '/static/WS.jpg', 'win_streak': r[2] or 0, 'bio': r[3] or ''} for r in c.fetchall()]
    emit('load_highest_streaks', top_users, room=request.sid)

@socketio.on('admin_get_recent_messages')
def handle_admin_get_recent_messages(data):
    admin_user = data.get('admin_user')
    if not check_is_admin(admin_user): return
    
    with sqlite3.connect('chat.db', timeout=10) as conn:
        c = conn.cursor()
        c.execute("SELECT id, sender, recipient, message, is_read FROM messages ORDER BY id DESC LIMIT 50")
        msgs = [{'id': r[0], 'sender': r[1], 'recipient': r[2] or 'Global Lounge', 'message': r[3], 'is_read': r[4]} for r in c.fetchall()]
    emit('load_admin_messages', msgs, room=request.sid)

@socketio.on('admin_delete_any_message')
def handle_admin_delete_any_message(data):
    admin_user = data.get('admin_user')
    msg_id = data.get('msg_id')
    if not check_is_admin(admin_user) or not msg_id: return
    
    with sqlite3.connect('chat.db', timeout=10) as conn:
        c = conn.cursor()
        c.execute("DELETE FROM messages WHERE id=?", (msg_id,))
        conn.commit()
    emit('message_deleted', msg_id, broadcast=True)

@socketio.on('admin_broadcast_msg')
def handle_admin_broadcast_msg(data):
    admin_user = data.get('admin_user')
    message = data.get('message', '').strip()
    if not check_is_admin(admin_user) or not message: return
    
    # 1. Send live floating system toast banner to all online users
    broadcast_payload = {
        'title': '📢 OFFICIAL SYSTEM ANNOUNCEMENT',
        'message': message,
        'sender': admin_user,
        'timestamp': datetime.datetime.now().strftime('%H:%M')
    }
    socketio.emit('system_broadcast_toast', broadcast_payload)
    
    # 2. Also send as an official system chat card in Global Lounge
    with sqlite3.connect('chat.db', timeout=10) as conn:
        c = conn.cursor()
        card_html = f'''<div class="system-broadcast-card" style="background: linear-gradient(135deg, rgba(236,72,153,0.3), rgba(139,92,246,0.3)); border: 2px solid #ec4899; border-radius: 20px; padding: 16px; margin: 10px 0; box-shadow: 0 10px 30px rgba(236,72,153,0.4);">
            <div style="font-weight: 900; color: #ec4899; font-size: 14px; margin-bottom: 6px; display: flex; align-items: center; gap: 8px;">
                <i class="fa-solid fa-bullhorn fa-bounce"></i> OFFICIAL SYSTEM ANNOUNCEMENT
            </div>
            <div style="color: #fff; font-size: 14px; font-weight: 600; line-height: 1.5;">{message}</div>
            <div style="font-size: 11px; color: rgba(255,255,255,0.6); margin-top: 8px; text-align: right;">Broadcast by @{admin_user}</div>
        </div>'''
        c.execute("INSERT INTO messages (sender, recipient, message) VALUES (?, '', ?)", (admin_user, card_html))
        conn.commit()
        msg_id = c.lastrowid
        
    socketio.emit('receive_message', {
        'id': msg_id,
        'user': admin_user,
        'recipient': None,
        'message': card_html,
        'is_read': 0,
        'reactions': {}
    })

@socketio.on('verify_secret_admin_pin')
def handle_verify_secret_admin_pin(data):
    admin_user = data.get('admin_user')
    pin = data.get('pin', '').strip()
    if pin == SECRET_ADMIN_PASSCODE:
        session['admin_key_unlocked'] = True
        with sqlite3.connect('chat.db', timeout=10) as conn:
            c = conn.cursor()
            c.execute("UPDATE users SET is_admin=1 WHERE username=?", (admin_user,))
            conn.commit()
        emit('secret_admin_pin_result', {'success': True}, room=request.sid)
    else:
        emit('secret_admin_pin_result', {'success': False, 'message': 'Incorrect Secret Admin Passcode!'}, room=request.sid)

if __name__ == '__main__':
    import os, socket
    port = int(os.environ.get('PORT', 5000))
    try:
        hostname = socket.gethostname()
        local_ip = socket.gethostbyname(hostname)
    except Exception:
        local_ip = "192.168.x.x"
        
    print("\n" + "="*65)
    print("WS CHAT MULTI-DEVICE SERVER IS LIVE!")
    print(f"LAPTOP / PC ACCESS:     http://localhost:{port}")
    print(f"MOBILE PHONE ACCESS:    http://{local_ip}:{port}")
    print("="*65 + "\n")
    socketio.run(app, host='0.0.0.0', port=port, debug=False, allow_unsafe_werkzeug=True)
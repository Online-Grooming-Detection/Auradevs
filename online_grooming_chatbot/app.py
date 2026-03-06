from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit, join_room, leave_room

app = Flask(__name__)
app.config['SECRET_KEY'] = 'safeguard-secret-key'
socketio = SocketIO(app, cors_allowed_origins="*")

# Track connected users: { sid: { name, avatar, room } }
users = {}

ROOM = "safeguard-room"

@app.route('/')
def index():
    return render_template('chat.html')

# ── User joins ──
@socketio.on('join')
def on_join(data):
    name = data.get('name', 'Anonymous')
    avatar = data.get('avatar', '🐼')
    sid = request.sid

    users[sid] = {'name': name, 'avatar': avatar, 'room': ROOM}
    join_room(ROOM)

    # Tell everyone else this user joined
    emit('user_joined', {'name': name, 'avatar': avatar}, to=ROOM, skip_sid=sid)

    # Send current user count back to the joiner
    count = len([u for u in users.values() if u['room'] == ROOM])
    emit('room_info', {'count': count, 'room': ROOM})

    print(f"[+] {name} joined | Total: {count}")

# ── Text message ──
@socketio.on('message')
def on_message(data):
    sid = request.sid
    user = users.get(sid, {})
    payload = {
        'name': user.get('name', 'Unknown'),
        'avatar': user.get('avatar', '🐼'),
        'text': data.get('text', ''),
        'sid': sid
    }
    # Broadcast to everyone in room including sender
    emit('message', payload, to=ROOM)
    print(f"[MSG] {user.get('name')}: {data.get('text', '')[:50]}")

# ── Image message ──
@socketio.on('image')
def on_image(data):
    sid = request.sid
    user = users.get(sid, {})
    payload = {
        'name': user.get('name', 'Unknown'),
        'avatar': user.get('avatar', '🐼'),
        'image': data.get('image', ''),   # base64 data URL
        'filename': data.get('filename', 'image'),
        'sid': sid
    }
    emit('image', payload, to=ROOM)
    print(f"[IMG] {user.get('name')} sent an image")

# ── Typing indicator ──
@socketio.on('typing')
def on_typing(data):
    sid = request.sid
    user = users.get(sid, {})
    emit('typing', {
        'name': user.get('name', ''),
        'typing': data.get('typing', False)
    }, to=ROOM, skip_sid=sid)

# ── Disconnect ──
@socketio.on('disconnect')
def on_disconnect():
    sid = request.sid
    user = users.pop(sid, {})
    if user:
        emit('user_left', {'name': user.get('name', '')}, to=ROOM)
        print(f"[-] {user.get('name')} left")

if __name__ == '__main__':
    print("=" * 45)
    print("  SafeGuard Chat Server")
    print("  Running on http://0.0.0.0:5000")
    print("  Share your IP address with the other device")
    print("=" * 45)
    socketio.run(app, host='0.0.0.0', port=3000, debug=True)
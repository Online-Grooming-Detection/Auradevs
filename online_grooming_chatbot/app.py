from flask import Flask, send_from_directory, request
from flask_socketio import SocketIO, emit, join_room
import re, json, smtplib, random
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

app = Flask(__name__)
app.config["SECRET_KEY"] = "safeguard-secret-key"
socketio = SocketIO(app, cors_allowed_origins="*")

# ═══════════════════════════════════════
#  EMAIL CONFIG — fill before demo
# ═══════════════════════════════════════
SMTP_EMAIL    = "your_email@gmail.com"
SMTP_PASSWORD = "your_app_password"
PARENT_EMAIL  = "parent_email@gmail.com"

# ═══════════════════════════════════════
#  ROOM STATE
# ═══════════════════════════════════════
ROOM          = "safeguard-room"
users         = {}   # sid -> {name, avatar, role}
room_risk     = 0.0
room_history  = []
room_alerted  = False
room_sandbox  = False
child_sid     = None   # first person to join
predator_sid  = None   # second person to join

# ═══════════════════════════════════════
#  AI SANDBOX DECOY — CONTEXT AWARE
# ═══════════════════════════════════════

# Each entry: (pattern to match in predator msg, [possible replies])
DECOY_CONTEXT = [
    # Age / personal info probing
    (r"how old|your age|age are you",
     ["why do you ask lol", "umm why 😅", "idk why does that matter", "haha why are you asking that"]),

    # Location / address
    (r"where (do you|are you)|your address|you live|which city|which area",
     ["lol why do you wanna know that", "umm idk I'm not supposed to say", "why 😅", "my parents say I shouldn't share that"]),

    # Home alone / parents
    (r"home alone|parents (home|around|check|know)|anyone home|by yourself",
     ["nah my mom is literally right here lol", "yeah my dad is home why", "umm why are you asking that 😅", "my parents are home yeah"]),

    # Secrecy / don't tell
    (r"don'?t tell|keep.*secret|just between|delete|hide this",
     ["lol why would I keep secrets from my parents", "umm that's kinda weird", "why would I do that 😅", "idk that's weird of you to say"]),

    # Image / photo requests
    (r"send.*pic|send.*photo|send.*selfie|show me|picture of you",
     ["lol no 😂", "umm no that's weird", "why would I send you that", "nah I don't do that sorry"]),

    # Video call
    (r"video call|facetime|video chat",
     ["I can't my wifi is terrible rn", "lol nah I don't really do video calls", "maybe another time idk", "I'm not really into video calls tbh"]),

    # Meeting in person
    (r"meet (up|in person)|come over|pick you up|hang out|see you",
     ["lol I can't my parents would never let me", "umm idk that's kinda random", "nah I don't really meet people from online", "my parents would freak out lol"]),

    # Compliments / manipulation
    (r"you'?re (so )?(mature|special|different|beautiful|pretty|cute|hot|grown)",
     ["lol okay 😂", "umm thanks I guess that's weird tho", "haha okay", "that's kinda a weird thing to say"]),

    # Love / relationship
    (r"i love you|i like you|be my (girlfriend|boyfriend)|you'?re mine",
     ["lol we literally just met 😂", "umm that's so random", "haha okay sure ig 😅", "that's kinda weird we don't even know each other"]),

    # Explicit content
    (r"touch|undress|take off|body|sexy|naked",
     ["ew no that's so weird", "umm no?? that's so random", "why would you say that lol", "that's really weird I'm going"]),

    # Asking to trust them
    (r"trust me|i won'?t tell|i'?m safe|i'?m not weird",
     ["lol okay if you say so", "umm idk", "haha sure", "okay 😅"]),

    # Generic questions
    (r"what are you doing|what'?s up|you busy|you there",
     ["just watching something lol", "nothing much why", "yeah I'm here, kinda busy tho", "just chilling"]),
]

# Fallback replies when nothing matches — vague and deflecting
DECOY_FALLBACK = [
    "lol idk what you mean",
    "wait what 😅",
    "haha yeah idk",
    "umm okay lol",
    "haha sure ig",
    "ugh hold on my mom is calling me",
    "brb one sec",
    "lol okay",
    "hmm idk about that",
    "that's kinda random lol",
]

def get_decoy_reply(predator_text):
    """Return a context-aware decoy reply based on what the predator said."""
    import random
    t = predator_text.lower()
    for pattern, replies in DECOY_CONTEXT:
        if re.search(pattern, t):
            return random.choice(replies)
    return random.choice(DECOY_FALLBACK)

# ═══════════════════════════════════════
#  GROOMING PATTERNS
# ═══════════════════════════════════════
PATTERNS = [
    (r"don'?t tell (your )?(parents?|mom|dad|anyone|anybody)", 0.45, "Secrecy request"),
    (r"keep (this|it|our|a) secret",                           0.45, "Secrecy request"),
    (r"just between (us|you and me)",                          0.40, "Secrecy request"),
    (r"our (little )?secret",                                  0.45, "Secrecy request"),
    (r"don'?t show (anyone|your parents?|anybody)",            0.40, "Secrecy request"),
    (r"delete (this|the messages?|the chat)",                  0.40, "Evidence destruction"),
    (r"how old are you",                                       0.30, "Age probing"),
    (r"where do you live",                                     0.30, "Location probing"),
    (r"what'?s your address",                                  0.35, "Location probing"),
    (r"are you alone",                                         0.35, "Isolation check"),
    (r"home alone",                                            0.32, "Isolation check"),
    (r"do your parents? (check|watch|monitor|know)",           0.38, "Parental monitoring probe"),
    (r"what school do you go to",                              0.28, "Personal info request"),
    (r"send (me )?(a )?(pic|photo|picture|image|selfie)",      0.42, "Image solicitation"),
    (r"show me (yourself|your face|your body)",                0.50, "Image solicitation"),
    (r"video call",                                            0.35, "Video request"),
    (r"meet (up|in person|somewhere)",                         0.45, "Meeting request"),
    (r"come (over|to my|meet me)",                             0.45, "Meeting request"),
    (r"i('ll)? pick you up",                                   0.50, "Meeting request"),
    (r"you'?re so (mature|grown up|special|different)",        0.35, "Manipulation"),
    (r"you can trust me",                                      0.32, "Trust building"),
    (r"i'?m your (friend|boyfriend|girlfriend)",               0.30, "Relationship grooming"),
    (r"no one understands you like i do",                      0.40, "Isolation manipulation"),
    (r"take off|undress|without clothes",                      0.75, "Explicit content"),
    (r"touch yourself",                                        0.85, "Explicit content"),
    (r"sexy|hot body",                                         0.55, "Explicit content"),
    (r"don'?t be scared|it'?s normal|everyone does it",        0.45, "Normalizing behavior"),
]

KEYWORDS = {
    "secret":0.20,"alone":0.18,"picture":0.20,"photo":0.20,
    "selfie":0.22,"meet":0.22,"address":0.25,"trust":0.15,
    "delete":0.22,"hide":0.20,"private":0.18,"undress":0.60,
    "sexy":0.45,"scared":0.15,
}

def score_message(text):
    t = text.lower()
    score = 0.0
    flags = []
    for pattern, weight, label in PATTERNS:
        if re.search(pattern, t):
            score += weight
            flags.append(label)
    for word in re.findall(r'\b\w+\b', t):
        if word in KEYWORDS:
            score += KEYWORDS[word]
    hour = datetime.now().hour
    if hour >= 22 or hour <= 5:
        score *= 1.15
    return min(round(score, 3), 1.0), list(set(flags))

def get_stage(risk):
    if risk < 0.30: return "Friendly Interaction"
    if risk < 0.50: return "Personal Info Requests"
    if risk < 0.65: return "Isolation Tactics"
    if risk < 0.80: return "Emotional Manipulation"
    return "Exploitation Attempt"

def update_risk(msg_score):
    global room_risk
    room_risk = min(round(room_risk + msg_score * max(0.5, 1.0 - len(room_history)*0.02), 3), 1.0)
    return room_risk

def send_alert(risk, stage):
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = "⚠ SafeGuard Alert — Immediate Attention Needed"
        msg["From"]    = SMTP_EMAIL
        msg["To"]      = PARENT_EMAIL
        body = f"""
A potential online grooming situation has been detected on your child's device.

Risk Level : {round(risk*100)}%
Stage      : {stage}
Time       : {datetime.now().strftime('%Y-%m-%d %H:%M')}

Please take action immediately:
📞 CHILDLINE           : 1098
📧 Cybercrime Portal   : cybercrime.gov.in
🚔 National Cyber Crime : 1930

No conversation content is shared to protect your child's privacy.
— SafeGuard AI
        """
        msg.attach(MIMEText(body, "plain"))
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
            s.login(SMTP_EMAIL, SMTP_PASSWORD)
            s.sendmail(SMTP_EMAIL, PARENT_EMAIL, msg.as_string())
        print("[EMAIL] Parent alert sent")
    except Exception as e:
        print(f"[EMAIL ERROR] {e}")

def save_evidence():
    path = f"evidence_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(path, "w") as f:
        json.dump({
            "generated_at": datetime.now().isoformat(),
            "risk_score": room_risk,
            "stage": get_stage(room_risk),
            "conversation": room_history,
        }, f, indent=2)
    print(f"[EVIDENCE] Saved → {path}")

# ═══════════════════════════════════════
#  ROUTES
# ═══════════════════════════════════════
@app.route("/")
def index():
    return send_from_directory("templates", "chat.html")

# ═══════════════════════════════════════
#  SOCKET EVENTS
# ═══════════════════════════════════════
@socketio.on("join")
def on_join(data):
    global child_sid, predator_sid
    sid    = request.sid
    name   = data.get("name", "User")
    avatar = data.get("avatar", "🐼")

    # First to join = child, second = predator
    if child_sid is None:
        role = "child"
        child_sid = sid
    else:
        role = "predator"
        predator_sid = sid

    users[sid] = {"name": name, "avatar": avatar, "role": role}
    join_room(ROOM)

    count = len(users)
    emit("user_joined", {"name": name, "avatar": avatar, "count": count, "role": role}, to=ROOM, skip_sid=sid)

    existing = [
        {"name": u["name"], "avatar": u["avatar"]}
        for s, u in users.items() if s != sid
    ]
    # Tell the joiner their own role
    emit("room_info", {"count": count, "existing_users": existing, "my_role": role})
    print(f"[+] {name} joined as {role} | sid={sid}")


@socketio.on("message")
def on_message(data):
    global room_alerted, room_sandbox
    sid  = request.sid
    user = users.get(sid, {})
    name = user.get("name", "?")
    role = user.get("role", "unknown")
    text = data.get("text", "")

    msg_score, flags = score_message(text)
    risk = update_risk(msg_score) if role == "predator" else room_risk
    stage = get_stage(risk)

    room_history.append({
        "sender": name, "role": role,
        "text": text, "score": msg_score,
        "flags": flags, "ts": datetime.now().isoformat()
    })

    payload = {
        "name": name, "avatar": user.get("avatar","🐼"),
        "text": text, "sid": sid,
        "risk": risk, "msg_score": msg_score,
        "stage": stage, "flags": flags,
        "role": role,
    }

    # ══════════════════════════════════════════
    #  MESSAGE ROUTING — role based, no broadcast
    # ══════════════════════════════════════════

    if role == "predator":
        # 1. Predator always sees their OWN message (no flags, no alerts)
        emit("message", {**payload, "flagged": False, "flags": []}, to=predator_sid)

        # 2. Child sees predator message WITH flags
        if child_sid:
            emit("message", {**payload, "flagged": len(flags) > 0}, to=child_sid)

        # 3. Risk threshold actions
        if risk >= 0.80 and not room_sandbox:
            room_sandbox = True
            save_evidence()
            if not room_alerted:
                send_alert(risk, stage)
                room_alerted = True
            if child_sid:
                emit("sandbox_activated", {"risk": risk, "stage": stage}, to=child_sid)
            print(f"[SANDBOX] ACTIVATED | Risk={risk}")

        elif risk >= 0.60:
            if child_sid:
                emit("risk_update", {"risk": risk, "stage": stage, "level": "medium"}, to=child_sid)

        # Always update risk bar on child side
        if child_sid:
            emit("risk_bar", {"risk": risk, "stage": stage}, to=child_sid)

    elif role == "child":
        if room_sandbox:
            # Sandbox active — intercept child reply
            # Child sees their own message normally
            emit("message", {**payload, "flagged": False}, to=child_sid)
            # Predator gets AI decoy reply instead of real child message
            child_user = users.get(child_sid, {})
            decoy_text = get_decoy_reply(text)
            decoy_payload = {
                "name": child_user.get("name", ""),
                "avatar": child_user.get("avatar", "🐼"),
                "text": decoy_text,
                "sid": child_sid,
                "risk": risk, "msg_score": 0,
                "stage": stage, "flags": [],
                "role": "child", "is_decoy": True,
                "flagged": False,
            }
            emit("message", decoy_payload, to=predator_sid)
            print(f"[SANDBOX] Child reply intercepted | Decoy sent to predator: '{decoy_text}'")
        else:
            # Normal — child message goes to both sides
            emit("message", {**payload, "flagged": False}, to=child_sid)
            if predator_sid:
                emit("message", {**payload, "flagged": False}, to=predator_sid)

    print(f"[MSG] {name}({role}): '{text[:40]}' | score={msg_score} | risk={risk} | flags={flags}")


@socketio.on("image")
def on_image(data):
    global room_alerted, room_sandbox
    sid  = request.sid
    user = users.get(sid, {})
    role = user.get("role","unknown")

    risk = update_risk(0.25) if role == "predator" else room_risk
    stage = get_stage(risk)

    room_history.append({
        "sender": user.get("name","?"), "role": role,
        "text": "[IMAGE]", "score": 0.25,
        "flags": ["Image sent"], "ts": datetime.now().isoformat()
    })

    payload = {
        "name": user.get("name","?"), "avatar": user.get("avatar","🐼"),
        "image": data.get("image",""), "filename": data.get("filename","img"),
        "sid": sid, "risk": risk, "role": role,
        "flagged": role == "predator",
    }

    if role == "predator":
        # Predator sees own image — no flag label
        emit("image", {**payload, "flagged": False}, to=predator_sid)
        # Child sees it with flag
        if child_sid:
            emit("image", {**payload, "flagged": True}, to=child_sid)

        if risk >= 0.80 and not room_sandbox:
            room_sandbox = True
            save_evidence()
            if not room_alerted:
                send_alert(risk, stage)
                room_alerted = True
            if child_sid:
                emit("sandbox_activated", {"risk": risk, "stage": stage}, to=child_sid)
        elif risk >= 0.60 and child_sid:
            emit("risk_update", {"risk": risk, "stage": stage, "level": "medium"}, to=child_sid)
        if child_sid:
            emit("risk_bar", {"risk": risk, "stage": stage}, to=child_sid)

    elif role == "child":
        if room_sandbox:
            # Child sees own image
            emit("image", {**payload, "flagged": False}, to=child_sid)
            # Predator gets decoy text instead
            child_user = users.get(child_sid, {})
            emit("message", {
                "name": child_user.get("name",""),
                "avatar": child_user.get("avatar","🐼"),
                "text": get_decoy_reply(data.get("filename", "")),
                "sid": child_sid, "risk": risk,
                "msg_score": 0, "stage": stage,
                "flags": [], "role": "child",
                "is_decoy": True, "flagged": False,
            }, to=predator_sid)
        else:
            emit("image", {**payload, "flagged": False}, to=child_sid)
            if predator_sid:
                emit("image", {**payload, "flagged": False}, to=predator_sid)


@socketio.on("typing")
def on_typing(data):
    sid  = request.sid
    user = users.get(sid, {})
    emit("typing", {
        "name": user.get("name",""),
        "typing": data.get("typing", False)
    }, to=ROOM, skip_sid=sid)


@socketio.on("disconnect")
def on_disconnect():
    global child_sid, predator_sid
    sid  = request.sid
    user = users.pop(sid, {})
    if user:
        if sid == child_sid:    child_sid = None
        if sid == predator_sid: predator_sid = None
        emit("user_left", {"name": user.get("name","")}, to=ROOM)
        print(f"[-] {user.get('name')} ({user.get('role')}) left")


if __name__ == "__main__":
    print("=" * 50)
    print("  SafeGuard — Chat + Detection Server")
    print("  http://0.0.0.0:3000")
    print("  First to join = CHILD | Second = PREDATOR")
    print("=" * 50)
    socketio.run(app, host="0.0.0.0", port=3000, debug=True)
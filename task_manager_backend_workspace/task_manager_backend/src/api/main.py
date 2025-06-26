from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from pydantic import BaseModel, Field, EmailStr
from typing import List, Optional
from datetime import datetime, timedelta
import sqlite3
import hashlib
import jwt
import os


# CONFIG
SECRET_KEY = os.getenv("SECRET_KEY", "scaletaskpro-secret-fallback")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30
SQLITE_DB_PATH = os.getenv("SQLITE_DB_PATH", "taskmanager.sqlite3")


# ---------------- Database Utility ----------------


def get_db_connection():
    """
    Returns a connection to the SQLite database.
    """
    conn = sqlite3.connect(SQLITE_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """
    Initializes the required tables if they do not exist.
    """
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        '''CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            hashed_password TEXT NOT NULL,
            full_name TEXT,
            is_active INTEGER DEFAULT 1
        )'''
    )
    c.execute(
        '''CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT,
            status TEXT NOT NULL DEFAULT 'todo',
            due_date TEXT,
            user_id INTEGER,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )'''
    )
    c.execute(
        '''CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            content TEXT NOT NULL,
            is_read INTEGER DEFAULT 0,
            sent_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )'''
    )
    conn.commit()
    conn.close()


init_db()


# ---------------- Helper Functions ----------------


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return hash_password(plain_password) == hashed_password


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta if expires_delta else timedelta(minutes=15))
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/token")


# ---------------- Pydantic Models ----------------


class UserBase(BaseModel):
    email: EmailStr = Field(..., description="User email address")
    full_name: Optional[str] = Field(None, description="Full name of the user")


class UserCreate(UserBase):
    password: str = Field(..., min_length=6, description="Password for the user")


class UserRead(UserBase):
    id: int
    is_active: bool


class UserEdit(BaseModel):
    full_name: Optional[str]
    password: Optional[str]


class TaskBase(BaseModel):
    title: str
    description: Optional[str]
    due_date: Optional[datetime]
    status: Optional[str] = Field(default="todo", description="Status: todo/in-progress/done")


class TaskCreate(TaskBase):
    pass


class TaskRead(TaskBase):
    id: int
    user_id: Optional[int]
    created_at: datetime
    updated_at: datetime


class TaskEdit(BaseModel):
    title: Optional[str]
    description: Optional[str]
    due_date: Optional[datetime]
    status: Optional[str]


class NotificationBase(BaseModel):
    content: str


class NotificationCreate(NotificationBase):
    pass


class NotificationRead(NotificationBase):
    id: int
    user_id: int
    is_read: bool
    sent_at: datetime


class Token(BaseModel):
    access_token: str
    token_type: str


class TokenData(BaseModel):
    user_id: Optional[int] = None


# ---------------- FastAPI App Setup ----------------


app = FastAPI(
    title="ScaletaskPro Task Manager Backend",
    description=(
        "Backend API for task management, user authentication, notifications, and health monitoring."
    ),
    version="1.0.0",
    openapi_tags=[
        {"name": "Tasks", "description": "Task management endpoints"},
        {"name": "Users", "description": "User management and authentication endpoints"},
        {"name": "Notifications", "description": "Send and view notifications"},
        {"name": "Health", "description": "Health check endpoints"},
    ],
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # For demo. In production, tighten this!
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------- Dependency Injection ----------------


def get_current_user(token: str = Depends(oauth2_scheme)) -> UserRead:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED, detail="Could not validate credentials"
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: int = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except Exception:
        raise credentials_exception

    conn = get_db_connection()
    user = conn.execute(
        "SELECT id, email, full_name, is_active FROM users WHERE id = ?", (user_id,)
    ).fetchone()
    conn.close()
    if not user:
        raise credentials_exception
    return UserRead(
        id=user["id"],
        email=user["email"],
        full_name=user["full_name"],
        is_active=bool(user["is_active"])
    )


# ---------------- USERS / AUTH ----------------

@app.post("/users/", response_model=UserRead, tags=["Users"], summary="Create a new user")
# PUBLIC_INTERFACE
def create_user(user: UserCreate):
    """
    Register a new user. Email must be unique.
    """
    conn = get_db_connection()
    try:
        conn.execute(
            "INSERT INTO users (email, hashed_password, full_name) VALUES (?, ?, ?)",
            (user.email, hash_password(user.password), user.full_name),
        )
        conn.commit()
        user_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(status_code=400, detail="Email already registered.")
    user_db = conn.execute(
        "SELECT id, email, full_name, is_active FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()
    conn.close()
    return UserRead(
        id=user_db["id"],
        email=user_db["email"],
        full_name=user_db["full_name"],
        is_active=bool(user_db["is_active"])
    )

@app.post("/auth/token", response_model=Token, tags=["Users"], summary="Get JWT token for authentication")
# PUBLIC_INTERFACE
def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends()):
    """
    Authenticate user and return JWT token.
    """
    conn = get_db_connection()
    user = conn.execute(
        "SELECT * FROM users WHERE email = ?", (form_data.username,)
    ).fetchone()
    conn.close()
    if not user or not verify_password(form_data.password, user["hashed_password"]):
        raise HTTPException(status_code=401, detail="Incorrect username or password")
    access_token = create_access_token(
        data={"sub": user["id"]},
        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    return Token(
        access_token=access_token,
        token_type="bearer"
    )







@app.get("/users/me/", response_model=UserRead, tags=["Users"], summary="Get current user")
# PUBLIC_INTERFACE
def read_current_user(current_user: UserRead = Depends(get_current_user)):
    """
    Returns the current authenticated user details.
    """
    return current_user

@app.get("/users/", response_model=List[UserRead], tags=["Users"], summary="List all users (ADMIN ONLY)")
# PUBLIC_INTERFACE
def list_users(current_user: UserRead = Depends(get_current_user)):
    """
    Get a list of all users. (For demo: No admin check!)
    """
    conn = get_db_connection()
    cursor = conn.execute(
        "SELECT id, email, full_name, is_active FROM users"
    )

    users = [
        UserRead(
            id=row["id"],
            email=row["email"],
            full_name=row["full_name"],
            is_active=bool(row["is_active"]),
        )
        for row in cursor.fetchall()
    ]
    conn.close()
    return users


@app.put("/users/me/", response_model=UserRead, tags=["Users"], summary="Edit user (update full name/password)")
# PUBLIC_INTERFACE
def update_user(user_update: UserEdit, current_user: UserRead = Depends(get_current_user)):
    """
    Update current user's profile (full name and/or password).
    """
    conn = get_db_connection()
    parameters = []
    sets = []
    if user_update.full_name:
        sets.append("full_name = ?")
        parameters.append(user_update.full_name)
    if user_update.password:
        sets.append("hashed_password = ?")
        parameters.append(hash_password(user_update.password))
    if not sets:
        raise HTTPException(status_code=400, detail="No changes specified.")
    parameters.append(current_user.id)
    conn.execute(f"UPDATE users SET {', '.join(sets)} WHERE id = ?", parameters)
    conn.commit()
    user = conn.execute(
        "SELECT id, email, full_name, is_active FROM users WHERE id = ?",
        (current_user.id,)
    ).fetchone()
    conn.close()
    return UserRead(id=user["id"], email=user["email"], full_name=user["full_name"], is_active=bool(user["is_active"]))

# ---------------- TASKS ----------------

@app.post("/tasks/", response_model=TaskRead, tags=["Tasks"], summary="Create a new task")
# PUBLIC_INTERFACE
def create_task(task: TaskCreate, current_user: UserRead = Depends(get_current_user)):
    """
    Create a new task and assign it to the current authenticated user.
    """
    now = datetime.utcnow().isoformat()
    conn = get_db_connection()
    c = conn.cursor()
    due = task.due_date.isoformat() if task.due_date else None
    c.execute(
        "INSERT INTO tasks "
        "(title, description, status, due_date, user_id, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            task.title,
            task.description,
            task.status,
            due,
            current_user.id,
            now,
            now
        ),
    )

    conn.commit()
    task_id = c.lastrowid
    row = c.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    conn.close()
    return TaskRead(
        id=row["id"],
        title=row["title"],
        description=row["description"],
        status=row["status"],
        due_date=(
            datetime.fromisoformat(row["due_date"]) if row["due_date"] else None
        ),
        user_id=row["user_id"],
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )




@app.get("/tasks/", response_model=List[TaskRead], tags=["Tasks"], summary="List my tasks")
# PUBLIC_INTERFACE
def list_my_tasks(current_user: UserRead = Depends(get_current_user)):
    """
    List all tasks assigned to the current user.
    """
    conn = get_db_connection()
    rows = conn.execute(
        "SELECT * FROM tasks WHERE user_id = ? ORDER BY due_date ASC, created_at DESC", (current_user.id,)
    ).fetchall()
    conn.close()
    return [
        TaskRead(
            id=row["id"],
            title=row["title"],
            description=row["description"],
            status=row["status"],
            due_date=(
                datetime.fromisoformat(row["due_date"])
                if row["due_date"]
                else None
            ),
            user_id=row["user_id"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )
        for row in rows
    ]


@app.get("/tasks/{task_id}/", response_model=TaskRead, tags=["Tasks"], summary="Get single task")
# PUBLIC_INTERFACE
def get_task(task_id: int, current_user: UserRead = Depends(get_current_user)):
    """
    Get one task by ID (must belong to current user).
    """
    conn = get_db_connection()
    row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    conn.close()
    if not row or row["user_id"] != current_user.id:
        raise HTTPException(status_code=404, detail="Task not found")
    return TaskRead(
        id=row["id"],
        title=row["title"],
        description=row["description"],
        status=row["status"],
        due_date=(
            datetime.fromisoformat(row["due_date"])
            if row["due_date"]
            else None
        ),
        user_id=row["user_id"],
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


@app.put("/tasks/{task_id}/", response_model=TaskRead, tags=["Tasks"], summary="Edit task")
# PUBLIC_INTERFACE
def edit_task(task_id: int, task: TaskEdit, current_user: UserRead = Depends(get_current_user)):
    """
    Edit a task's title, description, due date, or status.
    """
    conn = get_db_connection()
    row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if not row or row["user_id"] != current_user.id:
        conn.close()
        raise HTTPException(status_code=404, detail="Task not found")
    fields = []
    params = []
    if task.title:
        fields.append("title = ?")
        params.append(task.title)
    if task.description:
        fields.append("description = ?")
        params.append(task.description)
    if task.status:
        fields.append("status = ?")
        params.append(task.status)
    if task.due_date is not None:
        fields.append("due_date = ?")
        params.append(task.due_date.isoformat() if task.due_date else None)
    if not fields:
        conn.close()
        raise HTTPException(status_code=400, detail="Nothing to update.")
    fields.append("updated_at = ?")
    params.append(datetime.utcnow().isoformat())
    params.append(task_id)
    conn.execute(f"UPDATE tasks SET {', '.join(fields)} WHERE id = ?", params)
    conn.commit()
    row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    conn.close()
    return TaskRead(
        id=row["id"],
        title=row["title"],
        description=row["description"],
        status=row["status"],
        due_date=(
            datetime.fromisoformat(row["due_date"])
            if row["due_date"]
            else None
        ),
        user_id=row["user_id"],
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


@app.delete("/tasks/{task_id}/", status_code=204, tags=["Tasks"], summary="Delete task")
# PUBLIC_INTERFACE
def delete_task(task_id: int, current_user: UserRead = Depends(get_current_user)):
    """
    Delete a task (must be owned by current user).
    """
    conn = get_db_connection()
    row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if not row or row["user_id"] != current_user.id:
        conn.close()
        raise HTTPException(status_code=404, detail="Task not found")
    conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
    conn.commit()
    conn.close()
    return

# ---------------- NOTIFICATIONS ----------------

@app.post("/notifications/", response_model=NotificationRead, tags=["Notifications"], summary="Send notification")
# PUBLIC_INTERFACE
def create_notification(notification: NotificationCreate, current_user: UserRead = Depends(get_current_user)):
    """
    Send a notification to the current user.
    """
    now = datetime.utcnow().isoformat()
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        "INSERT INTO notifications (user_id, content, sent_at) VALUES (?, ?, ?)",
        (current_user.id, notification.content, now),
    )
    conn.commit()
    notif_id = c.lastrowid
    row = c.execute("SELECT * FROM notifications WHERE id = ?", (notif_id,)).fetchone()
    conn.close()
    return NotificationRead(
        id=row["id"],
        user_id=row["user_id"],
        content=row["content"],
        is_read=bool(row["is_read"]),
        sent_at=datetime.fromisoformat(row["sent_at"]),
    )


@app.get("/notifications/", response_model=List[NotificationRead], tags=["Notifications"], summary="View my notifications")
# PUBLIC_INTERFACE
def list_notifications(current_user: UserRead = Depends(get_current_user)):
    """
    List all notifications for the current user.
    """
    conn = get_db_connection()
    rows = conn.execute(
        "SELECT * FROM notifications WHERE user_id = ? ORDER BY sent_at DESC",
        (current_user.id,)
    ).fetchall()
    conn.close()
    return [
        NotificationRead(
            id=row["id"],
            user_id=row["user_id"],
            content=row["content"],
            is_read=bool(row["is_read"]),
            sent_at=datetime.fromisoformat(row["sent_at"]),
        )
        for row in rows
    ]


@app.put("/notifications/{notif_id}/read", response_model=NotificationRead, tags=["Notifications"], summary="Mark notification as read")
# PUBLIC_INTERFACE
def mark_notification_as_read(notif_id: int, current_user: UserRead = Depends(get_current_user)):
    """
    Mark a notification as read for the current user.
    """
    conn = get_db_connection()
    row = conn.execute("SELECT * FROM notifications WHERE id = ?", (notif_id,)).fetchone()
    if not row or row["user_id"] != current_user.id:
        conn.close()
        raise HTTPException(status_code=404, detail="Notification not found")
    conn.execute("UPDATE notifications SET is_read = 1 WHERE id = ?", (notif_id,))
    conn.commit()
    row = conn.execute("SELECT * FROM notifications WHERE id = ?", (notif_id,)).fetchone()
    conn.close()
    return NotificationRead(
        id=row["id"],
        user_id=row["user_id"],
        content=row["content"],
        is_read=bool(row["is_read"]),
        sent_at=datetime.fromisoformat(row["sent_at"]),
    )


# ---------------- HEALTH CHECK ----------------

@app.get("/health/db", tags=["Health"], summary="Check database health")
# PUBLIC_INTERFACE
def db_health_check():
    """
    Checks the health of the DB connection by running a simple query.
    Returns status=ok if connected, else status=fail.
    """

    try:
        conn = get_db_connection()
        conn.execute("SELECT 1")
        conn.close()
        return {"status": "ok"}
    except Exception:
        return JSONResponse(
            status_code=500,
            content={"status": "fail"},
        )


@app.get("/", tags=["Health"], summary="Service ready/Basic healthcheck")
def root():
    """Basic health check endpoint."""
    return {"message": "Healthy"}


# ---------------- Custom OpenAPI (adds WebSocket endpoint placeholder if needed) ----------------


def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
        tags=app.openapi_tags,
    )
    app.openapi_schema = openapi_schema
    return app.openapi_schema


app.openapi = custom_openapi


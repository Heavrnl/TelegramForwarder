from fastapi import APIRouter, Depends, HTTPException, status, Request, Response
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from models.models import get_session, User, RSSConfig
from models.db_operations import DBOperations
import jwt
from datetime import datetime, timedelta
import pytz
from utils.constants import DEFAULT_TIMEZONE
from typing import Optional
from sqlalchemy.orm import joinedload
import models.models as models
import os
import secrets
import hashlib
import hmac
import json
from urllib.parse import unquote, parse_qsl

router = APIRouter()
templates = Jinja2Templates(directory="rss/app/templates")
db_ops = None

# JWT configuration — persist SECRET_KEY across restarts so tokens survive server reloads
_key_file = os.path.join(os.path.dirname(__file__), '..', '..', '..', '..', 'db', '.jwt_secret')

def _load_or_create_secret_key() -> str:
    try:
        os.makedirs(os.path.dirname(_key_file), exist_ok=True)
        if os.path.exists(_key_file):
            with open(_key_file, 'r') as f:
                key = f.read().strip()
                if key:
                    return key
    except Exception:
        pass
    key = secrets.token_hex(32)
    try:
        with open(_key_file, 'w') as f:
            f.write(key)
    except Exception:
        pass
    return key

SECRET_KEY = _load_or_create_secret_key()
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 1440  # 24 hours

def init_db_ops():
    global db_ops
    if db_ops is None:
        db_ops = DBOperations()

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    tz = pytz.timezone(DEFAULT_TIMEZONE)
    if expires_delta:
        expire = datetime.now(tz) + expires_delta
    else:
        expire = datetime.now(tz) + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

async def get_current_user(request: Request):
    token = request.cookies.get("access_token")
    if not token:
        return None
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            return None
    except jwt.PyJWTError:
        return None
    
    db_session = get_session()
    try:
        init_db_ops()
        user = await db_ops.get_user(db_session, username)
        return user
    finally:
        db_session.close()

@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, user = Depends(get_current_user)):
    if user:
        return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
    
    db_session = get_session()
    try:
        # Check if any users exist
        users = db_session.query(User).all()
        if not users:
            return RedirectResponse(url="/register", status_code=status.HTTP_302_FOUND)
        return templates.TemplateResponse("login.html", {"request": request})
    finally:
        db_session.close()

@router.post("/login")
async def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    response: Response = None
):
    db_session = get_session()
    try:
        init_db_ops()
        user = await db_ops.verify_user(db_session, form_data.username, form_data.password)
        if not user:
            return templates.TemplateResponse(
                "login.html",
                {"request": request, "error": "Invalid username or password"},
                status_code=status.HTTP_401_UNAUTHORIZED
            )
        
        access_token = create_access_token(
            data={"sub": user.username},
            expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        )
        
        response = RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
        response.set_cookie(
            key="access_token",
            value=access_token,
            httponly=True,
            max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60
        )
        return response
    finally:
        db_session.close()

@router.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    db_session = get_session()
    try:
        # Check if a user already exists
        users = db_session.query(User).all()
        if users:
            return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
        return templates.TemplateResponse("register.html", {"request": request})
    finally:
        db_session.close()

@router.post("/register")
async def register(request: Request):
    form_data = await request.form()
    username = form_data.get("username")
    password = form_data.get("password")
    confirm_password = form_data.get("confirm_password")
    
    if password != confirm_password:
        return templates.TemplateResponse(
            "register.html",
            {"request": request, "error": "Passwords do not match"},
            status_code=status.HTTP_400_BAD_REQUEST
        )
    
    db_session = get_session()
    try:
        init_db_ops()
        user = await db_ops.create_user(db_session, username, password)
        if not user:
            return templates.TemplateResponse(
                "register.html",
                {"request": request, "error": "Failed to create user"},
                status_code=status.HTTP_400_BAD_REQUEST
            )
        
        access_token = create_access_token(
            data={"sub": user.username},
            expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        )
        
        response = RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
        response.set_cookie(
            key="access_token",
            value=access_token,
            httponly=True,
            max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60
        )
        return response
    finally:
        db_session.close()

@router.get("/logout")
async def logout():
    response = RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    response.delete_cookie("access_token")
    return response

@router.get("/", response_class=HTMLResponse)
async def index(request: Request, user = Depends(get_current_user)):
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    
    # Redirect to RSS dashboard
    return RedirectResponse(url="/rss/dashboard", status_code=status.HTTP_302_FOUND)

def _verify_telegram_init_data(init_data: str) -> Optional[dict]:
    """
    Verify Telegram WebApp initData using HMAC-SHA256.
    Returns parsed user dict on success, None on failure.
    See: https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
    """
    bot_token = os.getenv('BOT_TOKEN', '')
    if not bot_token:
        return None

    try:
        params = dict(parse_qsl(init_data, keep_blank_values=True))
        received_hash = params.pop('hash', None)
        if not received_hash:
            return None

        # Build the data-check-string: sorted key=value pairs joined by \n
        data_check_string = '\n'.join(
            f'{k}={v}' for k, v in sorted(params.items())
        )

        # secret_key = HMAC-SHA256("WebAppData", bot_token)
        secret_key = hmac.new(b'WebAppData', bot_token.encode(), hashlib.sha256).digest()
        computed_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

        if not hmac.compare_digest(computed_hash, received_hash):
            return None

        # Check auth_date freshness (allow up to 24 hours)
        auth_date = int(params.get('auth_date', 0))
        if abs(datetime.now().timestamp() - auth_date) > 86400:
            return None

        user_data = json.loads(params.get('user', '{}'))
        return user_data
    except Exception:
        return None


@router.post("/auth/telegram")
async def telegram_auth(request: Request):
    """
    Authenticate via Telegram WebApp initData.
    Called by the Mini App on load — verifies the Telegram-signed initData,
    creates a user account if needed, and sets a JWT cookie.
    """
    try:
        body = await request.json()
        init_data = body.get('initData', '')
    except Exception:
        return JSONResponse({'success': False, 'message': 'Invalid request body'}, status_code=400)

    user_data = _verify_telegram_init_data(init_data)
    if not user_data:
        return JSONResponse({'success': False, 'message': 'Invalid Telegram auth data'}, status_code=401)

    tg_id = user_data.get('id')
    tg_username = user_data.get('username') or f'tg_{tg_id}'
    username = f'tg_{tg_id}'  # Internal username keyed to Telegram ID

    db_session = get_session()
    try:
        init_db_ops()
        # Create user if this is their first login
        user = await db_ops.get_user(db_session, username)
        if not user:
            # Generate a random password — user never needs it (Telegram auth only)
            random_password = secrets.token_urlsafe(32)
            user = await db_ops.create_user(db_session, username, random_password)
            if not user:
                return JSONResponse({'success': False, 'message': 'Failed to create user'}, status_code=500)

        access_token = create_access_token(
            data={"sub": username},
            expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        )

        response = JSONResponse({'success': True, 'username': tg_username})
        response.set_cookie(
            key='access_token',
            value=access_token,
            httponly=True,
            max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            samesite='none',   # Required for cross-origin Mini App context
            secure=True        # Required when samesite=none
        )
        return response
    finally:
        db_session.close()


@router.post("/rss/change_password")
async def change_password(
    request: Request,
    user = Depends(get_current_user),
):
    """Change user password"""
    if not user:
        return JSONResponse(
            {"success": False, "message": "Not logged in or session expired"},
            status_code=status.HTTP_401_UNAUTHORIZED
        )
    
    try:
        form_data = await request.form()
        current_password = form_data.get("current_password")
        new_password = form_data.get("new_password")
        confirm_password = form_data.get("confirm_password")
        
        # Validate form data
        if not current_password:
            return JSONResponse({"success": False, "message": "Please enter your current password"})

        if not new_password:
            return JSONResponse({"success": False, "message": "Please enter a new password"})

        if len(new_password) < 8:
            return JSONResponse({"success": False, "message": "New password must be at least 8 characters"})

        if new_password != confirm_password:
            return JSONResponse({"success": False, "message": "New password and confirmation do not match"})
        
        # Verify current password
        db_session = get_session()
        try:
            init_db_ops()
            is_valid = await db_ops.verify_user(db_session, user.username, current_password)
            if not is_valid:
                return JSONResponse({"success": False, "message": "Current password is incorrect"})

            # Update password
            success = await db_ops.update_user_password(db_session, user.username, new_password)
            if not success:
                return JSONResponse({"success": False, "message": "Failed to change password, please try again"})

            return JSONResponse({"success": True, "message": "Password changed successfully"})
        finally:
            db_session.close()
    except Exception as e:
        return JSONResponse({"success": False, "message": f"Error changing password: {str(e)}"}) 
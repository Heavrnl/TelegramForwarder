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

router = APIRouter()
templates = Jinja2Templates(directory="rss/app/templates")
db_ops = None

# JWT configuration
SECRET_KEY = secrets.token_hex(32)
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
                {"request": request, "error": "Incorrect username or password"},
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
        # Check if users already exist
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

    # Redirect directly to the RSS dashboard
    return RedirectResponse(url="/rss/dashboard", status_code=status.HTTP_302_FOUND)

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
            return JSONResponse({"success": False, "message": "New password must be at least 8 characters long"})

        if new_password != confirm_password:
            return JSONResponse({"success": False, "message": "New password and confirmation password do not match"})

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

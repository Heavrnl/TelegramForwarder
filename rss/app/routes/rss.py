from fastapi import APIRouter, Depends, HTTPException, status, Request, Response, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from models.models import get_session, User, RSSConfig, ForwardRule, RSSPattern
from models.db_operations import DBOperations
from typing import Optional, List
from sqlalchemy.orm import joinedload
from .auth import get_current_user
from feedgen.feed import FeedGenerator
from datetime import datetime
import logging
import base64
import re
from utils.common import get_db_ops
import os
import aiohttp
from utils.constants import RSS_HOST, RSS_PORT, RSS_BASE_URL

# Configure logging
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/rss")
templates = Jinja2Templates(directory="rss/app/templates")
db_ops = None

async def init_db_ops():
    global db_ops
    if db_ops is None:
        db_ops = await get_db_ops()
    return db_ops

@router.get("/dashboard", response_class=HTMLResponse)
async def rss_dashboard(request: Request, user = Depends(get_current_user)):
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    
    db_session = get_session()
    try:
        # Initialize database operations
        await init_db_ops()

        # Fetch all RSS configs
        rss_configs = db_session.query(RSSConfig).options(
            joinedload(RSSConfig.rule)
        ).all()
        
        # Convert RSSConfig objects to list of dicts
        configs_list = []
        for config in rss_configs:
            # Encode AI extract prompt in Base64 to avoid JSON parsing issues
            ai_prompt = config.ai_extract_prompt
            ai_prompt_encoded = None
            if ai_prompt:
                # Base64-encode the prompt
                ai_prompt_encoded = base64.b64encode(ai_prompt.encode('utf-8')).decode('utf-8')
                # Add marker indicating Base64-encoded content
                ai_prompt_encoded = "BASE64:" + ai_prompt_encoded
            
            configs_list.append({
                "id": config.id,
                "rule_id": config.rule_id,
                "enable_rss": config.enable_rss,
                "rule_title": config.rule_title,
                "rule_description": config.rule_description,
                "language": config.language,
                "max_items": config.max_items,
                "is_auto_title": config.is_auto_title,
                "is_auto_content": config.is_auto_content,
                "is_ai_extract": config.is_ai_extract,
                "ai_extract_prompt": ai_prompt_encoded,
                "is_auto_markdown_to_html": config.is_auto_markdown_to_html,
                "enable_custom_title_pattern": config.enable_custom_title_pattern,
                "enable_custom_content_pattern": config.enable_custom_content_pattern
            })
        
        # Fetch all forwarding rules (for creating new RSS configs)
        rules = db_session.query(ForwardRule).options(
            joinedload(ForwardRule.source_chat),
            joinedload(ForwardRule.target_chat)
        ).all()

        # Convert ForwardRule objects to list of dicts
        rules_list = []
        for rule in rules:
            rules_list.append({
                "id": rule.id,
                "source_chat": {
                    "id": rule.source_chat.id,
                    "name": rule.source_chat.name
                } if rule.source_chat else None,
                "target_chat": {
                    "id": rule.target_chat.id,
                    "name": rule.target_chat.name
                } if rule.target_chat else None
            })
        
        return templates.TemplateResponse(
            "rss_dashboard.html", 
            {
                "request": request,
                "user": user,
                "rss_configs": configs_list,
                "rules": rules_list,
                "rss_base_url": RSS_BASE_URL or ""
            }
        )
    finally:
        db_session.close()

@router.post("/config", response_class=JSONResponse)
async def rss_config_save(
    request: Request,
    user = Depends(get_current_user),
    config_id: Optional[str] = Form(None),
    rule_id: int = Form(...),
    enable_rss: bool = Form(True),
    rule_title: str = Form(""),
    rule_description: str = Form(""),
    language: str = Form("zh-CN"),
    max_items: int = Form(50),
    is_auto_title: bool = Form(False),
    is_auto_content: bool = Form(False),
    is_ai_extract: bool = Form(False),
    ai_extract_prompt: str = Form(""),
    is_auto_markdown_to_html: bool = Form(False),
    enable_custom_title_pattern: bool = Form(False),
    enable_custom_content_pattern: bool = Form(False)
):
    if not user:
        return JSONResponse(content={"success": False, "message": "Not logged in"})
    
    # Log received AI extract prompt length for debugging
    logger.info(f"Received AI extract prompt length: {len(ai_extract_prompt)} chars")

    # Initialize database operations
    await init_db_ops()
    
    db_session = get_session()
    try:
        # Create or update RSS config
        # If config_id is present, update existing
        if config_id and config_id.strip():
            config_id = int(config_id)
            # Check if config exists
            rss_config = db_session.query(RSSConfig).filter(RSSConfig.id == config_id).first()
            if not rss_config:
                return JSONResponse(content={"success": False, "message": "Config not found"})
            
            # Update config fields
            rss_config.rule_id = rule_id
            rss_config.enable_rss = enable_rss
            rss_config.rule_title = rule_title
            rss_config.rule_description = rule_description
            rss_config.language = language
            rss_config.max_items = max_items
            rss_config.is_auto_title = is_auto_title
            rss_config.is_auto_content = is_auto_content
            rss_config.is_ai_extract = is_ai_extract
            rss_config.ai_extract_prompt = ai_extract_prompt
            rss_config.is_auto_markdown_to_html = is_auto_markdown_to_html
            rss_config.enable_custom_title_pattern = enable_custom_title_pattern
            rss_config.enable_custom_content_pattern = enable_custom_content_pattern
        else:
            # Check if a config already exists for this rule
            existing_config = db_session.query(RSSConfig).filter(RSSConfig.rule_id == rule_id).first()
            if existing_config:
                return JSONResponse(content={"success": False, "message": "An RSS config already exists for this rule"})

            # Create new config
            rss_config = RSSConfig(
                rule_id=rule_id,
                enable_rss=enable_rss,
                rule_title=rule_title,
                rule_description=rule_description,
                language=language,
                max_items=max_items,
                is_auto_title=is_auto_title,
                is_auto_content=is_auto_content,
                is_ai_extract=is_ai_extract,
                ai_extract_prompt=ai_extract_prompt,
                is_auto_markdown_to_html=is_auto_markdown_to_html,
                enable_custom_title_pattern=enable_custom_title_pattern,
                enable_custom_content_pattern=enable_custom_content_pattern
            )
        
        # Save config
        db_session.add(rss_config)
        db_session.commit()

        return JSONResponse({
            "success": True,
            "message": "RSS config saved",
            "config_id": rss_config.id,
            "rule_id": rss_config.rule_id
        })
    except Exception as e:
        return JSONResponse({"success": False, "message": f"Failed to save config: {str(e)}"})
    finally:
        db_session.close()

@router.get("/toggle/{rule_id}")
async def toggle_rss(rule_id: int, user = Depends(get_current_user)):
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    
    db_session = get_session()
    try:
        # Initialize database operations
        db_ops_instance = await init_db_ops()

        # Fetch config
        config = await db_ops_instance.get_rss_config(db_session, rule_id)
        if not config:
            return RedirectResponse(
                url="/rss/dashboard?error=Config+not+found",
                status_code=status.HTTP_302_FOUND
            )

        # Toggle enabled/disabled state
        await db_ops_instance.update_rss_config(
            db_session,
            rule_id,
            enable_rss=not config.enable_rss
        )
        
        return RedirectResponse(
            url="/rss/dashboard?success=RSS+status+toggled",
            status_code=status.HTTP_302_FOUND
        )
    finally:
        db_session.close()

@router.get("/delete/{rule_id}")
async def delete_rss(rule_id: int, user = Depends(get_current_user)):
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    
    db_session = get_session()
    try:
        # Initialize database operations
        db_ops_instance = await init_db_ops()

        # Delete config
        config_deleted = await db_ops_instance.delete_rss_config(db_session, rule_id)

        if config_deleted:
            # Delete associated media and data files
            try:
                logger.info(f"Deleting media and data files for rule {rule_id}")
                # Build the delete API URL
                rss_url = f"http://{RSS_HOST}:{RSS_PORT}/api/rule/{rule_id}"

                # Call the delete API
                async with aiohttp.ClientSession() as client_session:
                    async with client_session.delete(rss_url) as response:
                        if response.status == 200:
                            logger.info(f"Successfully deleted media and data files for rule {rule_id}")
                        else:
                            response_text = await response.text()
                            logger.warning(f"Failed to delete media/data files for rule {rule_id}, status: {response.status}, response: {response_text}")
            except Exception as e:
                logger.error(f"Error calling delete media files API: {str(e)}")
                # Non-fatal, continue

        return RedirectResponse(
            url="/rss/dashboard?success=RSS+config+deleted",
            status_code=status.HTTP_302_FOUND
        )
    finally:
        db_session.close()

@router.get("/patterns/{config_id}")
async def get_patterns(config_id: int, user = Depends(get_current_user)):
    """Get all patterns for the specified RSS config"""
    if not user:
        return JSONResponse({"success": False, "message": "Not logged in"}, status_code=status.HTTP_401_UNAUTHORIZED)
    
    db_session = get_session()
    try:
        # Initialize database operations
        db_ops_instance = await init_db_ops()

        # Fetch all pattern data
        config = await db_ops_instance.get_rss_config_with_patterns(db_session, config_id)
        if not config:
            return JSONResponse({"success": False, "message": "Config not found"}, status_code=status.HTTP_404_NOT_FOUND)

        # Convert patterns to JSON format
        patterns = []
        for pattern in config.patterns:
            patterns.append({
                "id": pattern.id,
                "pattern": pattern.pattern,
                "pattern_type": pattern.pattern_type,
                "priority": pattern.priority
            })
        
        return JSONResponse({"success": True, "patterns": patterns})
    finally:
        db_session.close()

@router.post("/pattern")
async def save_pattern(
    request: Request,
    user = Depends(get_current_user),
    pattern_id: Optional[str] = Form(None),
    rss_config_id: int = Form(...),
    pattern: str = Form(...),
    pattern_type: str = Form(...),
    priority: int = Form(0)
):
    """Save pattern"""
    logger.info(f"Saving pattern: config_id={rss_config_id}, pattern={pattern}, type={pattern_type}, priority={priority}")

    if not user:
        logger.warning("Unauthenticated access attempt")
        return JSONResponse({"success": False, "message": "Not logged in"}, status_code=status.HTTP_401_UNAUTHORIZED)
    
    db_session = get_session()
    try:
        # Initialize database operations
        db_ops_instance = await init_db_ops()

        # Check if RSS config exists
        config = await db_ops_instance.get_rss_config(db_session, rss_config_id)
        if not config:
            logger.error(f"RSS config not found: config_id={rss_config_id}")
            return JSONResponse({"success": False, "message": "RSS config not found"})

        logger.debug(f"Found RSS config: {config}")

        logger.info("Creating new pattern")
        # Create new pattern
        try:
            pattern_obj = await db_ops_instance.create_rss_pattern(
                db_session,
                config.id,
                pattern=pattern,
                pattern_type=pattern_type,
                priority=priority
            )
            logger.info(f"New pattern created: {pattern_obj}")
            return JSONResponse({"success": True, "message": "Pattern created", "pattern_id": pattern_obj.id})
        except Exception as e:
            logger.error(f"Failed to create pattern: {str(e)}")
            raise
    except Exception as e:
        logger.error(f"Error saving pattern: {str(e)}", exc_info=True)
        return JSONResponse({"success": False, "message": f"Failed to save pattern: {str(e)}"})
    finally:
        db_session.close()

@router.delete("/pattern/{pattern_id}")
async def delete_pattern(pattern_id: int, user = Depends(get_current_user)):
    """Delete pattern"""
    if not user:
        return JSONResponse({"success": False, "message": "Not logged in"}, status_code=status.HTTP_401_UNAUTHORIZED)

    db_session = get_session()
    try:
        # Initialize database operations
        await init_db_ops()

        # Query pattern
        pattern = db_session.query(RSSPattern).filter(RSSPattern.id == pattern_id).first()
        if not pattern:
            return JSONResponse({"success": False, "message": "Pattern not found"})

        # Delete pattern
        db_session.delete(pattern)
        db_session.commit()

        return JSONResponse({"success": True, "message": "Pattern deleted"})
    except Exception as e:
        db_session.rollback()
        logger.error(f"Error deleting pattern: {str(e)}")
        return JSONResponse({"success": False, "message": f"Failed to delete pattern: {str(e)}"})
    finally:
        db_session.close()

@router.delete("/patterns/{config_id}")
async def delete_all_patterns(config_id: int, user = Depends(get_current_user)):
    """Delete all patterns for a config, typically called before rebuilding the pattern list"""
    if not user:
        return JSONResponse({"success": False, "message": "Not logged in"}, status_code=status.HTTP_401_UNAUTHORIZED)

    db_session = get_session()
    try:
        # Initialize database operations
        await init_db_ops()

        # Query and delete all patterns for this config
        patterns = db_session.query(RSSPattern).filter(RSSPattern.rss_config_id == config_id).all()
        count = len(patterns)
        for pattern in patterns:
            db_session.delete(pattern)

        db_session.commit()
        logger.info(f"Deleted all {count} patterns for config {config_id}")

        return JSONResponse({"success": True, "message": f"Deleted {count} patterns"})
    except Exception as e:
        db_session.rollback()
        logger.error(f"Error deleting all patterns for config {config_id}: {str(e)}")
        return JSONResponse({"success": False, "message": f"Failed to delete all patterns: {str(e)}"})
    finally:
        db_session.close()

@router.post("/test-regex")
async def test_regex(user = Depends(get_current_user), 
                    pattern: str = Form(...), 
                    test_text: str = Form(...), 
                    pattern_type: str = Form(...)):
    """Test regex pattern match results"""
    if not user:
        return JSONResponse({"success": False, "message": "Not logged in"}, status_code=status.HTTP_401_UNAUTHORIZED)

    try:

        # Log test info
        logger.info(f"Testing regex: {pattern}")
        logger.info(f"Test type: {pattern_type}")
        logger.info(f"Test text length: {len(test_text)} chars")

        # Execute regex match
        match = re.search(pattern, test_text)

        # Check for match
        if not match:
            return JSONResponse({
                "success": True,
                "matched": False,
                "message": "No match found"
            })

        # Check capture groups
        if not match.groups():
            return JSONResponse({
                "success": True,
                "matched": True,
                "has_groups": False,
                "message": "Match found, but no capture groups. Use parentheses () to create capture groups."
            })

        # Successful match with capture groups
        extracted_content = match.group(1)

        # Return match results
        return JSONResponse({
            "success": True,
            "matched": True,
            "has_groups": True,
            "extracted": extracted_content,
            "message": "Match successful!"
        })

    except Exception as e:
        logger.error(f"Error testing regex: {str(e)}")
        return JSONResponse({
            "success": False,
            "message": f"Test failed: {str(e)}"
        }) 
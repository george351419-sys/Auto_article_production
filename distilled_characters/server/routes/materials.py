"""Material management routes — includes file upload."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Request

from core.models.character import MaterialCreate, MaterialUpdate
from core.utils.content_cleaner import clean_content, is_usable_content
from core.utils.file_parser import parse_bytesio
from server.dependencies import get_character_repo, get_material_repo

router = APIRouter(tags=["materials"])

# Max total upload size: 50MB
MAX_UPLOAD_BYTES = 50 * 1024 * 1024


@router.post("/characters/{character_id}/materials")
async def create_material(character_id: str, body: MaterialCreate):
    repo = get_material_repo()
    char_repo = get_character_repo()
    char = await char_repo.get(character_id)
    if not char:
        raise HTTPException(404, "Character not found")

    data = body.model_dump()
    data["character_id"] = character_id
    data["raw_content"] = clean_content(data.get("raw_content", ""))
    data["word_count"] = len(data.get("raw_content", ""))
    record = await repo.create(data)
    return record


@router.post("/characters/{character_id}/materials/upload")
async def upload_files(
    character_id: str,
    files: list[UploadFile] = File(...),
    source_type: str = Form("fragment_expression"),
    confidence: str = Form("B"),
):
    """Upload one or more files (PDF, TXT, DOCX, MD, etc.).

    Accepts multiple files in a single request. Each file is parsed
    into text and saved as a separate material record.
    """
    char_repo = get_character_repo()
    char = await char_repo.get(character_id)
    if not char:
        raise HTTPException(404, "Character not found")

    mat_repo = get_material_repo()
    results = []
    errors = []

    for file in files:
        # Read file content
        data = await file.read()
        if len(data) > MAX_UPLOAD_BYTES:
            errors.append({"filename": file.filename, "error": "文件过大 (最大50MB)"})
            continue

        # Parse file to text
        try:
            text = parse_bytesio(file.filename or "untitled", data)
        except ValueError as e:
            errors.append({"filename": file.filename, "error": str(e)})
            continue
        except Exception:
            errors.append({"filename": file.filename, "error": "文件解析失败，格式不支持"})
            continue

        # Clean CSS/HTML junk from scraped content
        text = clean_content(text)

        if not text.strip():
            errors.append({
                "filename": file.filename,
                "error": "解析结果为空（文件可能为扫描图片或加密PDF）",
            })
            continue

        if not is_usable_content(text):
            errors.append({
                "filename": file.filename,
                "error": f"有效内容不足（仅 {len(text)} 字符，需至少50个有效字符）。如果是纯代码/纯数据文件，请转为文本格式后上传。",
            })
            continue

        # Detect source_type from filename extension if not explicitly set
        detected_type = source_type
        if source_type == "fragment_expression" and file.filename:
            ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
            if ext in ("pdf", "docx", "doc"):
                detected_type = "systematic_output"

        try:
            record = await mat_repo.create({
                "character_id": character_id,
                "title": file.filename or "未命名文件",
                "raw_content": text,
                "source_type": detected_type,
                "confidence": confidence,
                "tags": ["file_upload"],
            })
            results.append({
                "id": record["id"],
                "filename": file.filename,
                "word_count": record.get("word_count", 0),
            })
        except Exception as e:
            errors.append({"filename": file.filename, "error": str(e)})

    return {
        "character_id": character_id,
        "uploaded": len(results),
        "failed": len(errors),
        "materials": results,
        "errors": errors,
    }


@router.get("/characters/{character_id}/materials")
async def list_materials(
    character_id: str,
    source_type: str = "",
    confidence: str = "",
):
    repo = get_material_repo()
    return await repo.list_for_character(
        character_id,
        source_type=source_type or None,
        confidence=confidence or None,
    )


@router.get("/materials/{material_id}")
async def get_material(material_id: str):
    repo = get_material_repo()
    record = await repo.get(material_id)
    if not record:
        raise HTTPException(404, "Material not found")
    return record


@router.put("/materials/{material_id}")
async def update_material(material_id: str, body: MaterialUpdate):
    repo = get_material_repo()
    existing = await repo.get(material_id)
    if not existing:
        raise HTTPException(404, "Material not found")
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    return await repo.update(material_id, updates)


@router.delete("/materials/{material_id}")
async def delete_material(material_id: str):
    repo = get_material_repo()
    existing = await repo.get(material_id)
    if not existing:
        raise HTTPException(404, "Material not found")
    await repo.delete(material_id)
    return {"deleted": True}

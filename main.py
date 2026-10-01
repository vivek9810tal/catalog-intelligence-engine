import json
import asyncio
from fastapi import FastAPI, HTTPException, Path
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from typing import Dict, List

load_dotenv(override=True)  # Load environment variables from .env file

from models import CatalogItem, EnrichedCatalogItem
from agent_workflow import run_orchestration

app = FastAPI(
    title="Catalog Intelligence Engine API",
    description="FastAPI gateway for multi-agent retail catalog enrichment.",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

async def get_catalog_db() -> dict:
    try:
        def read_json():
            with open("electronics.json", "r") as file:
                return json.load(file)
        return await asyncio.to_thread(read_json)
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="electronics.json database file not found.")
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail="electronics.json contains invalid JSON.")

@app.get("/health", tags=["System"])
async def health_check():
    return {"status": "healthy", "service": "Catalog Intelligence Engine"}

@app.get("/api/products", response_model=Dict[str, List[CatalogItem]], tags=["Catalog"])
async def get_all_products():
    return await get_catalog_db()

@app.post("/api/enrich/{brand}/{product_id}", response_model=EnrichedCatalogItem, tags=["Enrichment"])
async def enrich_product(
    brand: str = Path(..., description="The brand name"),
    product_id: str = Path(..., description="The unique product identifier")
):
    catalog = await get_catalog_db()
    
    if brand not in catalog:
        raise HTTPException(status_code=404, detail=f"Brand '{brand}' not found in catalog.")
        
    product_data = next((item for item in catalog[brand] if item["product_id"] == product_id), None)
    if not product_data:
        raise HTTPException(status_code=404, detail=f"Product ID '{product_id}' not found.")

    try:
        raw_item = CatalogItem(**product_data)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Data validation error: {str(e)}")

    initial_state = {
        "raw_item": raw_item,
        "assessment": None,
        "enriched_item": None,
        "workflow_status": "started",
        "messages": []
    }

    try:
        # Pass the state directly to the managed orchestration function
        final_state = await run_orchestration(initial_state)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Agent orchestration failed: {str(e)}")

    enriched_result = final_state.get("enriched_item")
    if not enriched_result:
        raise HTTPException(status_code=500, detail="Workflow completed but failed to return data.")

    return enriched_result
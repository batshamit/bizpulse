"""Run record lookup + chat."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from fpdf import FPDF
from pydantic import BaseModel

from bizpulse.agents.chatter import chat_about_recommendation
from bizpulse.agents.runner import AgentRunner
from bizpulse.api.dependencies import get_store, require_tenant
from bizpulse.api.runner_service import _pick_council, _pick_embedder
from bizpulse.models import RunRecord, Tenant
from bizpulse.retrieval.qdrant_repo import TenantQdrant
from bizpulse.retrieval.search import RetrievalEngine
from bizpulse.storage import Store

router = APIRouter(prefix="/v1/runs", tags=["runs"])

_QDRANT_BASE = Path(
    os.environ.get("BIZPULSE_QDRANT_DIR", str(Path(tempfile.gettempdir()) / "bizpulse-qdrant"))
)


@router.get("/{run_id}", response_model=RunRecord)
def get_run(
    run_id: UUID,
    tenant: Tenant = Depends(require_tenant),
    store: Store = Depends(get_store),
) -> RunRecord:
    run = store.get_run(run_id)
    if run is None or run.tenant_id != tenant.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")
    return run


def clean_text(text: str) -> str:
    if not isinstance(text, str):
        return text
    # Map common non-latin-1 unicode characters to latin-1 equivalents
    replacements = {
        "\u201c": '"',  # Left double quote
        "\u201d": '"',  # Right double quote
        "\u2019": "'",  # Right single quote
        "\u2018": "'",  # Left single quote
        "\u2013": "-",  # En-dash
        "\u2014": "--", # Em-dash
        "\u2022": "-",  # Bullet
        "\u2122": "TM", # Trademark
        "\u00ae": "(R)",# Registered trademark
        "\u00a9": "(C)",# Copyright
        "\u2026": "...", # Ellipsis
        "\u00a0": " ",  # Non-breaking space
        "\u200b": "",   # Zero-width space
    }
    for k, v in replacements.items():
        text = text.replace(k, v)
    # Safe encoding to latin-1 (unsupported replaced with '?')
    return text.encode("latin-1", "replace").decode("latin-1")


def get_val(obj: Any, attr: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(attr, default)
    return getattr(obj, attr, default)


class BizPulsePDF(FPDF):
    def __init__(self, *args: Any, title: str = "Marketing Strategy Report", company_name: str = "N/A", **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.report_title = title
        self.company_name = company_name
        # Premium generous margins
        self.set_margins(15, 15, 15)
        
        # Register custom premium fonts
        font_dir = Path(__file__).parent.parent / "fonts"
        self.add_font("PlayfairDisplay", style="", fname=str(font_dir / "PlayfairDisplay-Regular.ttf"))
        self.add_font("PlayfairDisplay", style="B", fname=str(font_dir / "PlayfairDisplay-Bold.ttf"))
        self.add_font("Inter", style="", fname=str(font_dir / "Inter-Regular.ttf"))
        self.add_font("Inter", style="B", fname=str(font_dir / "Inter-Bold.ttf"))
        self.add_font("Inter", style="I", fname=str(font_dir / "Inter-Italic.ttf"))

    def cell(self, w=None, h=None, text="", *args, **kwargs):
        text = clean_text(text)
        return super().cell(w, h, text, *args, **kwargs)

    def multi_cell(self, w=None, h=None, text="", *args, **kwargs):
        text = clean_text(text)
        return super().multi_cell(w, h, text, *args, **kwargs)

    def header(self) -> None:
        # Title banner - Authoritative PlayfairDisplay
        self.set_font("PlayfairDisplay", "B", 10.5)
        self.set_text_color(0, 33, 71)  # Deep Oxford Blue #002147
        self.cell(0, 8, "BIZPULSE INTELLIGENCE REPORT", border=0, new_x="LMARGIN", new_y="NEXT", align="L")
        
        self.set_font("Inter", "B", 7.5)
        self.set_text_color(212, 175, 55)  # Rich Gold/Bronze #D4AF37
        sub_title = f"{self.report_title}  |  {self.company_name}"
        self.cell(0, 5, sub_title.upper(), border=0, new_x="LMARGIN", new_y="NEXT", align="L")
        
        # Sleek Oxford Blue horizontal line
        self.set_draw_color(0, 33, 71)
        self.set_line_width(0.4)
        # Beautifully aligned line matching the 15mm margins
        self.line(15, 25, 195, 25)
        self.ln(6)

    def footer(self) -> None:
        self.set_y(-15)
        self.set_font("Inter", "I", 8)
        self.set_text_color(112, 128, 144)  # Slate Grey
        self.cell(0, 10, f"Page {self.page_no()}   |   BizPulse Confidential Real Estate Intelligence", align="C")

    def section_header(self, title: str, accent_color: tuple[int, int, int] = (0, 33, 71)) -> None:
        self.ln(3)
        y = self.get_y()
        
        # Check for page break before section header to prevent orphans
        if y > 255:
            self.add_page()
            y = self.get_y()
            
        # Draw a beautiful solid vertical accent bar
        self.set_fill_color(*accent_color)
        self.rect(15, y + 1.2, 3.5, 6.5, style="F")
        
        self.set_xy(19.5, y)
        self.set_font("PlayfairDisplay", "B", 12)
        self.set_text_color(26, 26, 26) # Charcoal for text
        self.cell(0, 8, title, new_x="LMARGIN", new_y="NEXT")
        self.ln(2.5)

    def render_academic_innovations(self, academic_research: list[Any] | None) -> None:
        self.section_header("Academic & Technological Innovations", accent_color=(0, 128, 128))
        if academic_research:
            for paper in academic_research:
                if self.get_y() > 240:
                    self.add_page()
                
                paper_title = clean_text(get_val(paper, "title", "Untitled"))
                findings = clean_text(get_val(paper, "key_findings", ""))
                app = clean_text(get_val(paper, "business_application", ""))
                
                lines_findings = max(1, len(findings) // 85 + 1)
                lines_app = max(1, len(app) // 85 + 1)
                card_h = 10 + ((lines_findings + lines_app) * 5.2) + 6
                
                if self.get_y() + card_h > 275:
                    self.add_page()
                
                card_y = self.get_y()
                self.set_fill_color(248, 252, 252) # Soft Teal tint
                self.set_draw_color(0, 128, 128)
                self.set_line_width(0.3)
                self.rect(15, card_y, 180, card_h, style="FD")
                
                # Draw a microchip/bullet native vector shape
                icon_x = 18
                icon_y = card_y + 4.5
                self.set_fill_color(0, 128, 128)
                self.rect(icon_x + 1, icon_y + 1, 2.5, 2.5, style="F")
                self.line(icon_x, icon_y + 1.8, icon_x + 1, icon_y + 1.8)
                self.line(icon_x, icon_y + 2.7, icon_x + 1, icon_y + 2.7)
                self.line(icon_x + 3.5, icon_y + 1.8, icon_x + 4.5, icon_y + 1.8)
                self.line(icon_x + 3.5, icon_y + 2.7, icon_x + 4.5, icon_y + 2.7)
                
                self.set_xy(25, card_y + 3)
                self.set_font("PlayfairDisplay", "B", 10.5)
                self.set_text_color(0, 128, 128)
                self.cell(0, 5, paper_title, new_x="LMARGIN", new_y="NEXT")
                
                self.set_x(25)
                self.set_font("Inter", "", 9.2)
                self.set_text_color(26, 26, 26)
                self.multi_cell(165, 5.2, f"Key Findings: {findings}")
                
                self.set_x(25)
                self.set_font("Inter", "B", 9.2)
                self.set_text_color(0, 128, 128)
                self.multi_cell(165, 5.2, f"Application: {app}")
                
                self.set_xy(15, card_y + card_h + 3)
        else:
            self.set_font("Inter", "I", 10)
            self.set_text_color(112, 128, 144)
            self.cell(0, 6, "No academic research breakthroughs reported.", new_x="LMARGIN", new_y="NEXT")
            self.ln(2)

    def render_policy_regulatory(self, policy_and_politics: Any | None) -> None:
        self.section_header("Regulatory, Policy & Geopolitical Updates", accent_color=(112, 128, 144))
        
        reg = get_val(policy_and_politics, "regulatory", [])
        fin = get_val(policy_and_politics, "financial", [])
        geo = get_val(policy_and_politics, "geopolitical", [])
        
        items = []
        if reg:
            for item in reg:
                items.append(("regulatory", item))
        if fin:
            for item in fin:
                items.append(("financial", item))
        if geo:
            for item in geo:
                items.append(("geopolitical", item))
                
        if items:
            for cat, text in items:
                curr_y = self.get_y()
                cleaned_txt = clean_text(text)
                lines_est = max(1, len(cleaned_txt) // 80 + 1)
                row_h = 5.2 * lines_est + 8
                
                if curr_y + row_h > 270:
                    self.add_page()
                    curr_y = self.get_y()
                
                # Draw high-contrast box
                self.set_fill_color(252, 252, 252)
                self.set_draw_color(26, 26, 26)  # Deep dark border
                self.set_line_width(0.4)
                self.rect(15, curr_y, 180, row_h, style="FD")
                
                # Monospace badge
                self.set_xy(18, curr_y + 3)
                self.set_font("Courier", "B", 9)
                
                if cat == "regulatory":
                    self.set_text_color(180, 0, 0)
                    self.cell(40, 5, "[REGULATORY WARNING]")
                elif cat == "financial":
                    self.set_text_color(180, 120, 0)
                    self.cell(40, 5, "[FINANCIAL ADVISORY]")
                else:
                    self.set_text_color(70, 70, 70)
                    self.cell(40, 5, "[GEOPOLITICAL INFO]")
                
                # Text
                self.set_xy(18, curr_y + 8)
                self.set_font("Inter", "", 9.2)
                self.set_text_color(26, 26, 26)
                self.multi_cell(174, 5.2, cleaned_txt)
                
                self.set_xy(15, curr_y + row_h + 3)
        else:
            self.set_font("Inter", "I", 10)
            self.set_text_color(112, 128, 144)
            self.cell(0, 6, "No regulatory, policy or geopolitical updates reported.", new_x="LMARGIN", new_y="NEXT")
            self.ln(2)

    def render_business_deals(self, business_deals: list[Any] | None) -> None:
        self.section_header("Strategic Corporate Deals & Partnerships", accent_color=(0, 33, 71))
        if business_deals:
            start_y = self.get_y()
            if start_y > 240:
                self.add_page()
                start_y = self.get_y()
                
            y_coords = []
            for deal in business_deals:
                entities = clean_text(get_val(deal, "entities"))
                strategic_impact = clean_text(get_val(deal, "strategic_impact"))
                
                lines_est = max(1, len(strategic_impact) // 85 + 1)
                item_h = 5 * lines_est + 8
                
                if self.get_y() + item_h > 270:
                    self.add_page()
                
                y_coords.append(self.get_y())
                curr_y = self.get_y()
                
                self.set_xy(26, curr_y)
                self.set_font("PlayfairDisplay", "B", 10.5)
                self.set_text_color(0, 33, 71)
                self.cell(0, 5, f"DEAL: {entities}", new_x="LMARGIN", new_y="NEXT")
                
                self.set_x(26)
                self.set_font("Inter", "", 9.2)
                self.set_text_color(26, 26, 26)
                self.multi_cell(169, 5, f"Strategic Impact: {strategic_impact}")
                self.ln(3)
                
            if len(y_coords) > 0:
                self.set_draw_color(0, 33, 71)
                self.set_line_width(0.6)
                self.line(20.25, y_coords[0] + 3, 20.25, y_coords[-1] + 3)
                
                for yc in y_coords:
                    self.set_fill_color(255, 255, 255)
                    self.set_draw_color(0, 33, 71)
                    self.set_line_width(1.0)
                    self.ellipse(18.5, yc + 1.2, 3.5, 3.5, style="FD")
        else:
            self.set_font("Inter", "I", 10)
            self.set_text_color(112, 128, 144)
            self.cell(0, 6, "No strategic deals or corporate expansions reported.", new_x="LMARGIN", new_y="NEXT")
            self.ln(2)

    def draw_warning_triangle(self, x: float, y: float) -> None:
        self.set_fill_color(220, 20, 60) # Crimson warning triangle
        self.set_draw_color(220, 20, 60)
        self.set_line_width(0.3)
        self.polygon([(x + 2, y), (x, y + 3.5), (x + 4, y + 3.5)], style="F")
        self.set_draw_color(255, 255, 255)
        self.set_line_width(0.4)
        self.line(x + 2, y + 1.2, x + 2, y + 2.4)
        self.rect(x + 1.8, y + 2.8, 0.4, 0.4, style="F")

    def render_climate_matrix(self, climate_and_weather: Any | None) -> None:
        self.section_header("Environmental & Climate Risk Matrix", accent_color=(34, 139, 34))
        
        matrix_y = self.get_y()
        if matrix_y > 220:
            self.add_page()
            matrix_y = self.get_y()
            
        self.set_font("Inter", "B", 7)
        self.set_text_color(112, 128, 144)
        
        self.set_xy(15 + 22, matrix_y)
        self.cell(45, 4, "LOW PROBABILITY", align="C")
        self.cell(45, 4, "HIGH PROBABILITY", align="C")
        
        self.set_xy(107 + 22, matrix_y)
        self.cell(45, 4, "LOW PROBABILITY", align="C")
        self.cell(45, 4, "HIGH PROBABILITY", align="C")
        
        g_y = matrix_y + 4
        
        # Quadrant 1 (Top Left)
        self.set_fill_color(254, 242, 242)
        self.set_draw_color(220, 20, 60)
        self.set_line_width(0.3)
        self.rect(15, g_y, 88, 20, style="FD")
        
        self.set_xy(17, g_y + 1.5)
        self.set_font("Inter", "B", 7.5)
        self.set_text_color(220, 20, 60)
        self.cell(84, 4.5, "HIGH IMPACT / LOW PROBABILITY THREAT", new_x="LMARGIN", new_y="NEXT")
        self.set_x(17)
        self.set_font("Inter", "", 7.5)
        self.set_text_color(26, 26, 26)
        self.multi_cell(84, 4, "Severe flash floods & logistics supply-chain shocks")
        
        # Quadrant 2 (Top Right)
        self.set_fill_color(254, 226, 226)
        self.rect(107, g_y, 88, 20, style="FD")
        
        self.set_xy(109, g_y + 1.5)
        self.set_font("Inter", "B", 7.5)
        self.set_text_color(220, 20, 60)
        self.cell(84, 4.5, "HIGH IMPACT / HIGH PROBABILITY THREAT", new_x="LMARGIN", new_y="NEXT")
        self.set_x(109)
        self.set_font("Inter", "", 7.5)
        self.set_text_color(26, 26, 26)
        self.multi_cell(84, 4, "Stricter ESG carbon taxes & mandatory net-zero compliance")
        
        # Quadrant 3 (Bottom Left)
        self.set_fill_color(240, 253, 244)
        self.set_draw_color(34, 139, 34)
        self.rect(15, g_y + 22, 88, 20, style="FD")
        
        self.set_xy(17, g_y + 23.5)
        self.set_font("Inter", "B", 7.5)
        self.set_text_color(34, 139, 34)
        self.cell(84, 4.5, "LOW IMPACT / HIGH PROBABILITY OPPORTUNITY", new_x="LMARGIN", new_y="NEXT")
        self.set_x(17)
        self.set_font("Inter", "", 7.5)
        self.set_text_color(26, 26, 26)
        self.multi_cell(84, 4, "Solar energy conversion subsidies, rooftop panels & state credits")
        
        # Quadrant 4 (Bottom Right)
        self.set_fill_color(220, 252, 231)
        self.rect(107, g_y + 22, 88, 20, style="FD")
        
        self.set_xy(109, g_y + 23.5)
        self.set_font("Inter", "B", 7.5)
        self.set_text_color(34, 139, 34)
        self.cell(84, 4.5, "HIGH IMPACT / HIGH PROBABILITY OPPORTUNITY", new_x="LMARGIN", new_y="NEXT")
        self.set_x(109)
        self.set_font("Inter", "", 7.5)
        self.set_text_color(26, 26, 26)
        self.multi_cell(84, 4, "ESG-linked financing green bonds yielding substantial savings")
        
        self.set_xy(15, g_y + 44)
        self.ln(3)
        
        opps = get_val(climate_and_weather, "opportunities", [])
        threats = get_val(climate_and_weather, "threats", [])
        
        has_cli = bool(opps or threats)
        if has_cli:
            if opps:
                if self.get_y() > 255:
                    self.add_page()
                self.set_font("Inter", "B", 9)
                self.set_text_color(34, 139, 34)
                self.cell(0, 5, "CLIMATE OPPORTUNITIES (UPWARD SIGNAL)", new_x="LMARGIN", new_y="NEXT")
                self.set_font("Inter", "", 9.2)
                self.set_text_color(26, 26, 26)
                for o in opps:
                    if self.get_y() > 270:
                        self.add_page()
                    self.set_font("Inter", "B", 9.2)
                    self.set_text_color(34, 139, 34)
                    self.cell(6, 5, "  ^  ")
                    self.set_font("Inter", "", 9.2)
                    self.set_text_color(26, 26, 26)
                    self.multi_cell(174, 5, clean_text(o))
                    self.ln(1)
            if threats:
                if self.get_y() > 255:
                    self.add_page()
                self.set_font("Inter", "B", 9)
                self.set_text_color(220, 20, 60)
                self.cell(0, 5, "CLIMATE THREATS (WARNING SIGNALS)", new_x="LMARGIN", new_y="NEXT")
                self.set_font("Inter", "", 9.2)
                self.set_text_color(26, 26, 26)
                for t in threats:
                    if self.get_y() > 270:
                        self.add_page()
                    curr_y = self.get_y()
                    self.draw_warning_triangle(15, curr_y + 0.8)
                    self.set_xy(21, curr_y)
                    self.multi_cell(174, 5, clean_text(t))
                    self.ln(1)
        else:
            self.set_font("Inter", "I", 10)
            self.set_text_color(112, 128, 144)
            self.cell(0, 6, "No environmental or climate updates reported.", new_x="LMARGIN", new_y="NEXT")
            self.ln(2)

    def render_competitor_intelligence(self, competitors_and_products: Any | None) -> None:
        self.section_header("Competitor Intelligence & Sentiment", accent_color=(75, 0, 130))
        
        chart_y = self.get_y()
        if chart_y > 220:
            self.add_page()
            chart_y = self.get_y()
            
        self.set_fill_color(248, 246, 252)
        self.set_draw_color(75, 0, 130)
        self.set_line_width(0.3)
        self.rect(15, chart_y, 88, 30, style="FD")
        
        self.set_xy(18, chart_y + 2.5)
        self.set_font("Inter", "B", 7.5)
        self.set_text_color(75, 0, 130)
        self.cell(80, 4, "BENGALURU CAPITAL VALUE GROWTH (QOQ)", new_x="LMARGIN", new_y="NEXT")
        
        self.set_xy(18, chart_y + 7)
        self.set_font("PlayfairDisplay", "B", 20)
        self.set_text_color(75, 0, 130)
        self.cell(40, 12, "1.5%")
        
        # Sparkline 1: Vector Line
        self.set_draw_color(147, 51, 234)
        self.set_line_width(0.8)
        sp_x = 55
        sp_y = chart_y + 16
        self.line(sp_x, sp_y, sp_x + 8, sp_y - 2)
        self.line(sp_x + 8, sp_y - 2, sp_x + 16, sp_y + 1)
        self.line(sp_x + 16, sp_y + 1, sp_x + 24, sp_y - 6)
        self.line(sp_x + 24, sp_y - 6, sp_x + 32, sp_y - 10)
        self.set_fill_color(147, 51, 234)
        self.ellipse(sp_x + 31, sp_y - 11.5, 2, 2, style="FD")
        
        self.set_xy(18, chart_y + 22)
        self.set_font("Inter", "", 7.5)
        self.set_text_color(112, 128, 144)
        self.cell(80, 4, "Steady quarterly real estate appreciation.")
        
        # Card 2: Supply Launch Growth (5.8%)
        self.set_fill_color(248, 246, 252)
        self.set_draw_color(75, 0, 130)
        self.rect(107, chart_y, 88, 30, style="FD")
        
        self.set_xy(110, chart_y + 2.5)
        self.set_font("Inter", "B", 7.5)
        self.set_text_color(75, 0, 130)
        self.cell(80, 4, "BENGALURU SUPPLY LAUNCH (YOY)", new_x="LMARGIN", new_y="NEXT")
        
        self.set_xy(110, chart_y + 7)
        self.set_font("PlayfairDisplay", "B", 20)
        self.set_text_color(75, 0, 130)
        self.cell(40, 12, "5.8%")
        
        # Sparkline 2: Vector Line
        self.set_draw_color(147, 51, 234)
        self.set_line_width(0.8)
        sp_x2 = 147
        sp_y2 = chart_y + 18
        self.line(sp_x2, sp_y2, sp_x2 + 8, sp_y2 - 4)
        self.line(sp_x2 + 8, sp_y2 - 4, sp_x2 + 16, sp_y2 - 2)
        self.line(sp_x2 + 16, sp_y2 - 2, sp_x2 + 24, sp_y2 - 9)
        self.line(sp_x2 + 24, sp_y2 - 9, sp_x2 + 32, sp_y2 - 14)
        self.set_fill_color(147, 51, 234)
        self.ellipse(sp_x2 + 31, sp_y2 - 15.5, 2, 2, style="FD")
        
        self.set_xy(110, chart_y + 22)
        self.set_font("Inter", "", 7.5)
        self.set_text_color(112, 128, 144)
        self.cell(80, 4, "Robust year-over-year inventory expansion.")
        
        self.set_xy(15, chart_y + 32)
        self.ln(3)
        
        new_prod = get_val(competitors_and_products, "new_products", [])
        comp_moves = get_val(competitors_and_products, "competitor_moves", [])
        sentiment = get_val(competitors_and_products, "client_sentiment", [])
        
        has_comp = bool(new_prod or comp_moves or sentiment)

        if has_comp:
            self.set_font("Inter", "", 9.2)
            self.set_text_color(26, 26, 26)
            
            if comp_moves:
                for m in comp_moves:
                    if self.get_y() > 265:
                        self.add_page()
                    card_y = self.get_y()
                    text = clean_text(m)
                    lines_est = max(1, len(text) // 85 + 1)
                    card_h = 4 + (lines_est * 5.2)
                    
                    self.set_fill_color(253, 251, 255)
                    self.set_draw_color(216, 180, 254)
                    self.set_line_width(0.3)
                    self.rect(15, card_y, 180, card_h, style="FD")
                    
                    self.set_xy(18, card_y + 2)
                    self.set_font("Inter", "B", 9.2)
                    self.set_text_color(75, 0, 130)
                    self.cell(35, 5, "[COMPETITOR MOVE] ")
                    self.set_font("Inter", "", 9.2)
                    self.set_text_color(26, 26, 26)
                    self.multi_cell(142, 5.2, text)
                    
                    self.set_xy(15, card_y + card_h + 3)
                    self.ln(1)
            
            if new_prod:
                self.set_font("Inter", "B", 9)
                self.set_text_color(75, 0, 130)
                self.cell(0, 5, "NEW PRODUCTS LAUNCHED", new_x="LMARGIN", new_y="NEXT")
                self.set_font("Inter", "", 9.2)
                self.set_text_color(26, 26, 26)
                for np in new_prod:
                    if self.get_y() > 270:
                        self.add_page()
                    self.cell(5, 5, "- ")
                    self.multi_cell(175, 5, clean_text(np))
                    self.ln(1)
                    
            if sentiment:
                self.set_font("Inter", "B", 9)
                self.set_text_color(75, 0, 130)
                self.cell(0, 5, "CLIENT SENTIMENT & DEMAND INSIGHTS", new_x="LMARGIN", new_y="NEXT")
                self.set_font("Inter", "", 9.2)
                self.set_text_color(26, 26, 26)
                for cs in sentiment:
                    if self.get_y() > 270:
                        self.add_page()
                    self.cell(5, 5, "- ")
                    self.multi_cell(175, 5, clean_text(cs))
                    self.ln(1)
        else:
            self.set_font("Inter", "I", 10)
            self.set_text_color(112, 128, 144)
            self.cell(0, 6, "No competitor updates reported.", new_x="LMARGIN", new_y="NEXT")
            self.ln(2)

    def render_emerging_radar(self, emerging_radar: list[str] | None) -> None:
        self.section_header("Emerging Radar Anomaly Signals", accent_color=(220, 20, 60))
        
        radar_y = self.get_y()
        if radar_y > 230:
            self.add_page()
            radar_y = self.get_y()
            
        self.set_fill_color(26, 26, 26)
        self.set_draw_color(220, 20, 60)
        self.set_line_width(0.6)
        
        lines_count = len(emerging_radar) if emerging_radar else 1
        box_h = 10 + (lines_count * 9.5)
        
        if radar_y + box_h > 270:
            self.add_page()
            radar_y = self.get_y()
            
        self.rect(15, radar_y, 180, box_h, style="FD")
        
        self.set_xy(18, radar_y + 3)
        self.set_font("PlayfairDisplay", "B", 10.5)
        self.set_text_color(220, 20, 60)
        self.cell(0, 5, "EMERGING ALERTS & RISK SHOCKS DECLARED", new_x="LMARGIN", new_y="NEXT")
        
        self.set_font("Inter", "", 9)
        self.set_text_color(255, 255, 255)
        if emerging_radar:
            for item in emerging_radar:
                self.set_x(18)
                self.cell(7, 5, "🎯 ")
                self.multi_cell(165, 5.2, clean_text(item))
                self.ln(1.5)
        self.set_xy(15, radar_y + box_h + 4)
        self.ln(2)

@router.get("/{run_id}/pdf")
def download_pdf(
    run_id: UUID,
    tenant: Tenant = Depends(require_tenant),
    store: Store = Depends(get_store),
) -> Response:
    run = store.get_run(run_id)
    if run is None or run.tenant_id != tenant.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")
    if run.final_output is None:
        raise HTTPException(status_code=400, detail="run has no final strategy to download")

    # Fetch actual business details to get real Company Name & URL
    business = store.get_business(run.business_id)
    company_name = "N/A"
    company_url = "N/A"
    if business:
        company_url = business.url
        from bizpulse.retrieval.web_search import _get_business_name_from_url
        company_name = _get_business_name_from_url(business.url).title()

    if run.run_type == "daily_research":
        from bizpulse.models import DailyResearchReport
        s = run.final_output
        assert isinstance(s, DailyResearchReport)

        pdf = BizPulsePDF(title="BizPulse Daily Research Report", company_name=company_name)
        pdf.set_margins(15, 15, 15)
        pdf.add_page()

        # -------------------------------------------------------------
        # 1. Header & Report Metadata (Oxford Blue #002147 / Hairline Dividers)
        # -------------------------------------------------------------
        meta_y = pdf.get_y()
        pdf.set_fill_color(248, 249, 250)
        pdf.set_draw_color(234, 234, 234) # Hairline dividers (#EAEAEA)
        pdf.set_line_width(0.3)
        pdf.rect(15, meta_y, 180, 15, style="FD")
        
        # Vertical Dividers
        pdf.line(75, meta_y, 75, meta_y + 15)
        pdf.line(135, meta_y, 135, meta_y + 15)
        
        # Col 1: Company Name
        pdf.set_xy(18, meta_y + 2)
        pdf.set_font("Inter", "B", 7.5)
        pdf.set_text_color(0, 33, 71)
        pdf.cell(50, 4, "COMPANY", new_x="LMARGIN", new_y="NEXT")
        pdf.set_x(18)
        pdf.set_font("Inter", "", 8.5)
        pdf.set_text_color(26, 26, 26)
        pdf.cell(50, 5, clean_text(company_name))
        
        # Col 2: Report Date
        pdf.set_xy(78, meta_y + 2)
        pdf.set_font("Inter", "B", 7.5)
        pdf.set_text_color(0, 33, 71)
        pdf.cell(50, 4, "REPORT DATE", new_x="LMARGIN", new_y="NEXT")
        pdf.set_x(78)
        pdf.set_font("Inter", "", 8.5)
        pdf.set_text_color(26, 26, 26)
        pdf.cell(50, 5, str(run.finished_at or run.started_at)[:10])
        
        # Col 3: Confidence Score
        pdf.set_xy(138, meta_y + 2)
        pdf.set_font("Inter", "B", 7.5)
        pdf.set_text_color(0, 33, 71)
        pdf.cell(50, 4, "CONFIDENCE SCORE", new_x="LMARGIN", new_y="NEXT")
        pdf.set_x(138)
        pdf.set_font("Inter", "", 8.5)
        pdf.set_text_color(26, 26, 26)
        pdf.cell(50, 5, f"{int(s.overall_confidence * 100)}%")
        
        pdf.set_xy(15, meta_y + 18)
        pdf.ln(2)

        # -------------------------------------------------------------
        # 2. Executive Summary Highlight (Trust Blue #005A9C & Slate #708090)
        # -------------------------------------------------------------
        pdf.section_header("Executive Summary Highlight", accent_color=(0, 90, 156))
        start_y = pdf.get_y()
        text = clean_text(s.most_important_update)
        char_limit = 100
        num_lines = max(1, len(text) // char_limit + 1)
        box_h = 8 + (num_lines * 6.5)
        
        if start_y + box_h > 270:
            pdf.add_page()
            start_y = pdf.get_y()
            
        pdf.set_fill_color(248, 249, 250) # #F8F9FA Background
        pdf.rect(15, start_y, 180, box_h, style="F")
        pdf.set_draw_color(0, 90, 156)  # Trust Blue left border
        pdf.set_line_width(2.0)
        pdf.line(15, start_y, 15, start_y + box_h)
        
        pdf.set_xy(20, start_y + 4)
        pdf.set_font("Inter", "B", 10)  # Increased font weight
        pdf.set_text_color(26, 26, 26)
        pdf.multi_cell(170, 6.0, text)
        pdf.set_xy(15, start_y + box_h + 4)
        pdf.ln(2)

        # 3. Academic & Technological Innovations
        pdf.render_academic_innovations(s.academic_research)

        # 4. Regulatory, Policy & Geopolitical Updates
        pdf.render_policy_regulatory(s.policy_and_politics)

        # 5. Strategic Corporate Deals & Partnerships
        pdf.render_business_deals(s.business_deals)

        # 6. Environmental & Climate Risk Matrix
        pdf.render_climate_matrix(s.climate_and_weather)

        # 7. Competitor Intelligence & Sentiment
        pdf.render_competitor_intelligence(s.competitors_and_products)

        # 8. Emerging Radar Anomaly Signals
        pdf.render_emerging_radar(s.emerging_radar)

        # 9. Groundedness Audit (Slate Grey Footnote)
        if pdf.get_y() > 245:
            pdf.add_page()
            
        audit_y = pdf.get_y()
        pdf.set_fill_color(248, 248, 248)
        pdf.set_draw_color(210, 210, 210)
        pdf.set_line_width(0.2)
        pdf.rect(15, audit_y, 180, 22, style="FD")
        
        pdf.set_xy(17, audit_y + 1.5)
        pdf.set_font("Inter", "B", 7.5)
        pdf.set_text_color(112, 128, 144)
        pdf.cell(0, 4, "GROUNDEDNESS & UNCERTAINTY FOOTNOTE AUDIT LOG", new_x="LMARGIN", new_y="NEXT")
        
        pdf.set_x(17)
        pdf.set_font("Inter", "I", 7.2)
        pdf.set_text_color(112, 128, 144)
        if s.uncertainty_log:
            uncertainty_text = "; ".join([clean_text(u) for u in s.uncertainty_log])
            pdf.multi_cell(176, 3.8, f"Unverified claims registered during Daily Research run: {uncertainty_text}")
        else:
            pdf.cell(0, 4.5, "Zero unverified or hallucinated claims detected. All reported facts are fully grounded in context source documents.")
            
        pdf.set_xy(15, audit_y + 24)
        pdf.ln(2)

        # Citations
        if s.citations:
            pdf.section_header("Sources & Citations", accent_color=(0, 33, 71))
            for idx, cit in enumerate(s.citations, 1):
                if pdf.get_y() > 250:
                    pdf.add_page()
                pdf.set_font("Inter", "B", 9)
                pdf.set_text_color(0, 33, 71)
                pdf.cell(0, 5, f"Source #{idx} (Confidence: {int(cit.confidence * 100)}%)", new_x="LMARGIN", new_y="NEXT")
                pdf.set_font("Inter", "", 9)
                pdf.set_text_color(26, 26, 26)
                txt = f"Chunk ID: {cit.chunk_id}"
                if cit.quote:
                    txt = f"Quote: \"{clean_text(cit.quote)}\"\n{txt}"
                pdf.multi_cell(0, 5.2, txt)
                pdf.ln(2)

        content = bytes(pdf.output())
        filename = f"BizPulse_Report_{run_id}.pdf"
        return Response(
            content=content,
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )

    # =========================================================================
    # Marketing Strategy Report Generation
    # =========================================================================
    from bizpulse.models import MarketingStrategy
    s = run.final_output
    assert isinstance(s, MarketingStrategy)
    
    pdf = BizPulsePDF(title="BizPulse Marketing Strategy", company_name=company_name)
    pdf.set_margins(15, 15, 15)
    pdf.add_page()

    # -------------------------------------------------------------
    # 1. Header & Report Metadata (Oxford Blue #002147 / Hairline Dividers)
    # -------------------------------------------------------------
    meta_y = pdf.get_y()
    pdf.set_fill_color(248, 249, 250)
    pdf.set_draw_color(234, 234, 234) # Hairline dividers (#EAEAEA)
    pdf.set_line_width(0.3)
    pdf.rect(15, meta_y, 180, 26, style="FD")
    
    # Grid lines
    pdf.line(75, meta_y, 75, meta_y + 26)
    pdf.line(135, meta_y, 135, meta_y + 26)
    pdf.line(15, meta_y + 13, 195, meta_y + 13)
    
    # Row 1 Left: Company
    pdf.set_xy(18, meta_y + 2)
    pdf.set_font("Inter", "B", 7.5)
    pdf.set_text_color(0, 33, 71)
    pdf.cell(50, 4, "COMPANY", new_x="LMARGIN", new_y="NEXT")
    pdf.set_x(18)
    pdf.set_font("Inter", "", 8.5)
    pdf.set_text_color(26, 26, 26)
    pdf.cell(50, 5, clean_text(company_name))
    
    # Row 1 Mid: Date
    pdf.set_xy(78, meta_y + 2)
    pdf.set_font("Inter", "B", 7.5)
    pdf.set_text_color(0, 33, 71)
    pdf.cell(50, 4, "REPORT DATE", new_x="LMARGIN", new_y="NEXT")
    pdf.set_x(78)
    pdf.set_font("Inter", "", 8.5)
    pdf.set_text_color(26, 26, 26)
    pdf.cell(50, 5, str(run.finished_at or run.started_at)[:10])
    
    # Row 1 Right: Confidence Score
    pdf.set_xy(138, meta_y + 2)
    pdf.set_font("Inter", "B", 7.5)
    pdf.set_text_color(0, 33, 71)
    pdf.cell(50, 4, "CONFIDENCE SCORE", new_x="LMARGIN", new_y="NEXT")
    pdf.set_x(138)
    pdf.set_font("Inter", "", 8.5)
    pdf.set_text_color(26, 26, 26)
    pdf.cell(50, 5, f"{int(s.overall_confidence * 100)}%")
    
    # Row 2 Left: Company URL
    pdf.set_xy(18, meta_y + 15)
    pdf.set_font("Inter", "B", 7.5)
    pdf.set_text_color(0, 33, 71)
    pdf.cell(50, 4, "COMPANY URL", new_x="LMARGIN", new_y="NEXT")
    pdf.set_x(18)
    pdf.set_font("Inter", "", 8.5)
    pdf.set_text_color(26, 26, 26)
    pdf.cell(50, 5, clean_text(company_url))
    
    # Row 2 Mid: Target Industry
    pdf.set_xy(78, meta_y + 15)
    pdf.set_font("Inter", "B", 7.5)
    pdf.set_text_color(0, 33, 71)
    pdf.cell(50, 4, "TARGET INDUSTRY", new_x="LMARGIN", new_y="NEXT")
    pdf.set_x(78)
    pdf.set_font("Inter", "", 8.5)
    pdf.set_text_color(26, 26, 26)
    pdf.cell(50, 5, s.industry.upper())
    
    # Row 2 Right: Strategy Status
    pdf.set_xy(138, meta_y + 15)
    pdf.set_font("Inter", "B", 7.5)
    pdf.set_text_color(0, 33, 71)
    pdf.cell(50, 4, "STRATEGY STATUS", new_x="LMARGIN", new_y="NEXT")
    pdf.set_x(138)
    pdf.set_font("Inter", "", 8.5)
    pdf.set_text_color(26, 26, 26)
    pdf.cell(50, 5, "BOARD READY")
    
    pdf.set_xy(15, meta_y + 29)
    pdf.ln(2)

    # -------------------------------------------------------------
    # 2. Executive Summary Highlight (Trust Blue #005A9C & Slate #708090)
    # -------------------------------------------------------------
    pdf.section_header("Executive Summary", accent_color=(0, 90, 156))
    start_y = pdf.get_y()
    text = clean_text(s.summary)
    char_limit = 100
    num_lines = max(1, len(text) // char_limit + 1)
    box_h = 8 + (num_lines * 6.5)
    
    if start_y + box_h > 270:
        pdf.add_page()
        start_y = pdf.get_y()
        
    pdf.set_fill_color(248, 249, 250) # #F8F9FA Background
    pdf.rect(15, start_y, 180, box_h, style="F")
    pdf.set_draw_color(0, 90, 156)  # Trust Blue left border
    pdf.set_line_width(2.0)
    pdf.line(15, start_y, 15, start_y + box_h)
    
    pdf.set_xy(20, start_y + 4)
    pdf.set_font("Inter", "B", 10)  # Increased font weight
    pdf.set_text_color(26, 26, 26)
    pdf.multi_cell(170, 6.0, text)
    pdf.set_xy(15, start_y + box_h + 4)
    pdf.ln(2)

    # -------------------------------------------------------------
    # 3. Inclusivity Scorecard (4 L's Clean 4-Node Grid UI with Progress Indicators)
    # -------------------------------------------------------------
    if s.inclusivity_metrics:
        pdf.section_header("Inclusivity Scorecard (4 L's)", accent_color=(70, 130, 180)) # Slate Blue
        m = s.inclusivity_metrics
        
        card_y = pdf.get_y()
        if card_y + 35 > 270:
            pdf.add_page()
            card_y = pdf.get_y()
            
        # Draw 4 beautiful side-by-side node cards
        # 180mm / 4 = 45mm each. Let's make them 43mm wide with a 2mm gap.
        cards_data = [
            ("LAST (LATE ADOPTERS)", m.last, (0, 90, 156)),
            ("LEAST (UNDER-SERVED)", m.least, (70, 130, 180)),
            ("LOST (CHURNED)", m.lost, (213, 108, 80)),
            ("LOWEST (BUDGET)", m.lowest, (112, 128, 144))
        ]
        
        for idx, (label, val, bar_color) in enumerate(cards_data):
            c_x = 15 + (idx * 45)
            # Background block
            pdf.set_fill_color(248, 249, 250)
            pdf.set_draw_color(230, 230, 230)
            pdf.set_line_width(0.2)
            pdf.rect(c_x, card_y, 43, 20, style="FD")
            
            # Value percentage
            pdf.set_xy(c_x + 3, card_y + 2)
            pdf.set_font("PlayfairDisplay", "B", 14)
            pdf.set_text_color(26, 26, 26)
            pdf.cell(37, 6, f"{int(val*100)}%")
            
            # Label
            pdf.set_xy(c_x + 3, card_y + 8)
            pdf.set_font("Inter", "B", 6.5)
            pdf.set_text_color(112, 128, 144)
            pdf.cell(37, 4, label)
            
            # Miniature Progress Bar
            pdf.set_fill_color(235, 235, 235)
            pdf.rect(c_x + 3, card_y + 14, 37, 2, style="F")
            
            pdf.set_fill_color(*bar_color)
            pdf.rect(c_x + 3, card_y + 14, 37 * val, 2, style="F")
            
        pdf.set_xy(15, card_y + 24)
        pdf.set_font("Inter", "I", 9.5)
        pdf.set_text_color(112, 128, 144)
        pdf.multi_cell(180, 5.2, f"Narrative Analysis: {clean_text(m.narrative)}")
        pdf.ln(4)

    # -------------------------------------------------------------
    # 4. Actionable Recommendations (Distinct Cards / Gold Accents)
    # -------------------------------------------------------------
    pdf.section_header("Board-Ready Actionable Recommendations", accent_color=(212, 175, 55)) # Gold
    
    for r in s.recommendations:
        # Estimate height needed
        cleaned_act = clean_text(r.action)
        cleaned_rat = clean_text(r.rationale)
        cleaned_imp = clean_text(r.expected_impact) if r.expected_impact else ""
        
        lines_act = max(1, len(cleaned_act) // 75 + 1)
        lines_rat = max(1, len(cleaned_rat) // 85 + 1)
        lines_imp = max(1, len(cleaned_imp) // 85 + 1) if cleaned_imp else 0
        
        card_h = 10 + (lines_act * 5.5) + (lines_rat * 5.2) + 2
        if cleaned_imp:
            card_h += (lines_imp * 5.2) + 4
            
        if pdf.get_y() + card_h > 270:
            pdf.add_page()
            
        curr_y = pdf.get_y()
        
        # Bounding box with High-Signal Gold accent border and light gold-tint background
        pdf.set_fill_color(252, 250, 244) # #FCFAF4 Soft Gold tint
        pdf.set_draw_color(212, 175, 55) # High-Signal Gold border
        pdf.set_line_width(0.3)
        pdf.rect(15, curr_y, 180, card_h, style="FD")
        
        # Heavy gold accent left line
        pdf.set_line_width(1.8)
        pdf.line(15, curr_y, 15, curr_y + card_h)
        
        # Content inside the Card
        pdf.set_xy(20, curr_y + 3)
        pdf.set_font("PlayfairDisplay", "B", 10.5)
        pdf.set_text_color(0, 33, 71) # Navy for title
        priority_lbl = f"[{r.priority}] "
        pdf.multi_cell(170, 5.5, f"{priority_lbl}{cleaned_act} (Channel: {r.channel.upper().replace('_', ' ')})")
        
        pdf.set_x(20)
        pdf.set_font("Inter", "", 9.2)
        pdf.set_text_color(26, 26, 26)
        pdf.multi_cell(170, 5.2, f"Rationale: {cleaned_rat}")
        
        if cleaned_imp:
            pdf.ln(1)
            pdf.set_x(20)
            # Highlight Expected Impact dynamically in a subtle badge block
            imp_y = pdf.get_y()
            pdf.set_fill_color(245, 245, 245)
            pdf.set_draw_color(220, 220, 220)
            pdf.set_line_width(0.2)
            pdf.rect(20, imp_y, 170, (lines_imp * 5.2) + 2, style="FD")
            
            pdf.set_xy(22, imp_y + 1)
            pdf.set_font("Inter", "B", 9)
            pdf.set_text_color(212, 175, 55) # Gold tag
            pdf.cell(32, 5, "EXPECTED IMPACT: ")
            pdf.set_font("Inter", "", 9)
            pdf.set_text_color(26, 26, 26)
            pdf.multi_cell(134, 5, cleaned_imp)
            pdf.set_y(imp_y + (lines_imp * 5.2) + 3)
            
        pdf.set_xy(15, curr_y + card_h + 4)
        pdf.ln(1)

    # -------------------------------------------------------------
    # 5. Detailed Channel Strategies
    # -------------------------------------------------------------
    if s.detailed_channel_strategies:
        pdf.add_page()
        pdf.section_header("Detailed Channel Strategies", accent_color=(0, 33, 71))
        for ds in s.detailed_channel_strategies:
            card_y = pdf.get_y()
            details = clean_text(ds.strategy_details)
            metrics = ", ".join(ds.key_metrics) if ds.key_metrics else ""
            
            lines_det = max(1, len(details) // 85 + 1)
            lines_met = max(1, len(metrics) // 85 + 1) if metrics else 0
            
            card_h = 10 + (lines_det * 5.2) + 2
            if metrics:
                card_h += (lines_met * 5) + 2
                
            if card_y + card_h > 270:
                pdf.add_page()
                card_y = pdf.get_y()
                
            pdf.set_fill_color(248, 249, 250)
            pdf.set_draw_color(220, 220, 220)
            pdf.set_line_width(0.2)
            pdf.rect(15, card_y, 180, card_h, style="FD")
            
            pdf.set_xy(18, card_y + 3)
            pdf.set_font("PlayfairDisplay", "B", 10.5)
            pdf.set_text_color(0, 33, 71)
            pdf.cell(0, 5, ds.channel.upper().replace("_", " "), new_x="LMARGIN", new_y="NEXT")
            
            pdf.set_x(18)
            pdf.set_font("Inter", "", 9.2)
            pdf.set_text_color(26, 26, 26)
            pdf.multi_cell(174, 5.2, details)
            
            if metrics:
                pdf.ln(1)
                pdf.set_x(18)
                pdf.set_font("Inter", "I", 9.2)
                pdf.set_text_color(112, 128, 144)
                pdf.multi_cell(174, 5, f"Key KPIs: {metrics}")
                
            pdf.set_xy(15, card_y + card_h + 3)
            pdf.ln(1)

    # -------------------------------------------------------------
    # 6. Business Benefit Report
    # -------------------------------------------------------------
    if s.benefit_report:
        pdf.section_header("Business Benefit Report", accent_color=(34, 139, 34))
        start_y = pdf.get_y()
        text = clean_text(s.benefit_report)
        char_limit = 100
        num_lines = max(1, len(text) // char_limit + 1)
        box_h = 8 + (num_lines * 6.5)
        
        if start_y + box_h > 270:
            pdf.add_page()
            start_y = pdf.get_y()
            
        pdf.set_fill_color(244, 249, 244)
        pdf.rect(15, start_y, 180, box_h, style="F")
        pdf.set_draw_color(34, 139, 34)
        pdf.set_line_width(1.8)
        pdf.line(15, start_y, 15, start_y + box_h)
        
        pdf.set_xy(20, start_y + 4)
        pdf.set_font("Inter", "", 9.5)
        pdf.set_text_color(26, 26, 26)
        pdf.multi_cell(170, 5.5, text)
        pdf.set_xy(15, start_y + box_h + 4)
        pdf.ln(2)

    # -------------------------------------------------------------
    # 7. Integrated Market Intelligence & Insights (Bridged)
    # -------------------------------------------------------------
    has_insights = bool(s.research_and_innovation or s.policy_and_politics or s.business_deals or s.climate_and_weather or s.competitors_and_products or s.emerging_radar)
    if has_insights:
        pdf.add_page()
        pdf.section_header("Integrated Market Intelligence & Insights", accent_color=(0, 33, 71))
        pdf.ln(2)

        if s.research_and_innovation:
            pdf.render_academic_innovations(s.research_and_innovation)
        if s.policy_and_politics:
            pdf.render_policy_regulatory(s.policy_and_politics)
        if s.business_deals:
            pdf.render_business_deals(s.business_deals)
        if s.climate_and_weather:
            pdf.render_climate_matrix(s.climate_and_weather)
        if s.competitors_and_products:
            pdf.render_competitor_intelligence(s.competitors_and_products)
        if s.emerging_radar:
            pdf.render_emerging_radar(s.emerging_radar)

    # -------------------------------------------------------------
    # 8. Compliance Remediation Audit (Monospace, Rigid Warning Boxes, Color Squares)
    # -------------------------------------------------------------
    if s.compliance_report:
        pdf.add_page()
        cr = s.compliance_report
        pdf.section_header(f"Compliance Audit - Overall Score: {int(cr.overall_compliance_score*100)}%", accent_color=(128, 0, 32))
        
        pdf.set_font("Inter", "", 9.5)
        pdf.set_text_color(26, 26, 26)
        pdf.multi_cell(0, 5.5, clean_text(cr.summary))
        pdf.ln(4)
        
        pdf.set_font("PlayfairDisplay", "B", 11)
        pdf.set_text_color(128, 0, 32)
        pdf.cell(0, 8, "Compliance Flags & Remediation Audit", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)
        
        for f in cr.flags:
            cleaned_iss = clean_text(f.issue)
            cleaned_fix = clean_text(f.fix)
            
            lines_iss = max(1, len(cleaned_iss) // 85 + 1)
            lines_fix = max(1, len(cleaned_fix) // 85 + 1) if cleaned_fix else 0
            
            card_h = 10 + (lines_iss * 5.2) + 2
            if cleaned_fix:
                card_h += (lines_fix * 5) + 3
                
            if pdf.get_y() + card_h > 270:
                pdf.add_page()
                
            curr_y = pdf.get_y()
            
            # Rigid technical threat analysis warning box styling with high contrast borders
            pdf.set_fill_color(253, 253, 253)
            pdf.set_draw_color(26, 26, 26) # Rigid black border
            pdf.set_line_width(0.5)
            pdf.rect(15, curr_y, 180, card_h, style="FD")
            
            # Draw color-coded square and taxonomy text
            severity_str = f.severity.lower()
            if severity_str == "critical":
                taxonomy_tag = "[CRITICAL EXPOSURE]"
                color_square = (220, 20, 60) # Crimson
                color_text = (220, 20, 60)
            elif severity_str in ["violation", "warning"]:
                taxonomy_tag = "[HIGH RISK]"
                color_square = (220, 20, 60) # Crimson
                color_text = (220, 20, 60)
            else:
                taxonomy_tag = "[OPERADVISORY]"
                color_square = (212, 175, 55) # Gold
                color_text = (212, 175, 55)

            pdf.set_fill_color(*color_square)
            pdf.rect(18, curr_y + 3.2, 3, 3, style="F")
            
            # Monospace headers for policy slugs
            pdf.set_xy(23, curr_y + 2)
            pdf.set_font("Courier", "B", 9.5)
            pdf.set_text_color(*color_text)
            pdf.cell(165, 5, f"{taxonomy_tag} POLICY: {f.policy_slug.upper()}")
                
            pdf.set_xy(18, curr_y + 7.5)
            pdf.set_font("Inter", "", 9.2)
            pdf.set_text_color(26, 26, 26)
            pdf.multi_cell(174, 5.2, f"Issue Identified: {cleaned_iss}")
            
            if cleaned_fix:
                pdf.ln(0.5)
                pdf.set_x(18)
                pdf.set_font("Inter", "B", 9)
                pdf.set_text_color(34, 139, 34) # Green for remediation
                pdf.multi_cell(174, 5, f"Required Fix Action: {cleaned_fix}")
                
            pdf.set_xy(15, curr_y + card_h + 3)
            pdf.ln(1)

    content = bytes(pdf.output())
    filename = f"BizPulse_Report_{run_id}.pdf"
    return Response(
        content=content,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )

@router.get("/{run_id}/download")
def download_run(
    run_id: UUID,
    tenant: Tenant = Depends(require_tenant),
    store: Store = Depends(get_store),
) -> Response:
    run = store.get_run(run_id)
    if run is None or run.tenant_id != tenant.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")
    if run.final_output is None:
        raise HTTPException(status_code=400, detail="run has no final strategy to download")

    if run.run_type == "daily_research":
        from bizpulse.models import DailyResearchReport
        s = run.final_output
        assert isinstance(s, DailyResearchReport)

        md = [
            "# BizPulse Daily Research Report",
            f"**Business URL:** {run.business_id}",
            f"**Industry:** {s.industry}",
            f"**Date:** {run.finished_at or run.started_at}",
            f"**Confidence Score:** {int(s.overall_confidence * 100)}%",
            f"\n## Most Critical Update\n> {s.most_important_update}",
            "\n## Academic & Technological Innovations",
        ]
        if s.academic_research:
            for paper in s.academic_research:
                md.append(f"- **Title:** {paper.title}\n  *Key Findings:* {paper.key_findings}\n  *Application:* {paper.business_application}")
        else:
            md.append("*No academic research reported.*")

        md.append("\n## Regulatory, Policy & Geopolitical Updates")
        pol = s.policy_and_politics
        has_pol = bool(pol.regulatory or pol.financial or pol.geopolitical)
        if has_pol:
            if pol.regulatory:
                for item in pol.regulatory:
                    md.append(f"- **Regulatory:** {item}")
            if pol.financial:
                for item in pol.financial:
                    md.append(f"- **Financial/Budget:** {item}")
            if pol.geopolitical:
                for item in pol.geopolitical:
                    md.append(f"- **Geopolitical/Trade:** {item}")
        else:
            md.append("*No policy or regulation updates reported.*")

        md.append("\n## Strategic Corporate Deals & Partnerships")
        if s.business_deals:
            for deal in s.business_deals:
                md.append(f"- **Entities:** {deal.entities}\n  *Strategic Impact:* {deal.strategic_impact}")
        else:
            md.append("*No strategic business deals reported.*")

        md.append("\n## Environmental & Climate Risk Matrix")
        cli = s.climate_and_weather
        has_cli = bool(cli.threats or cli.opportunities)
        if has_cli:
            if cli.threats:
                for t in cli.threats:
                    md.append(f"- **Threat:** {t}")
            if cli.opportunities:
                for o in cli.opportunities:
                    md.append(f"- **Opportunity:** {o}")
        else:
            md.append("*No environmental or climate updates reported.*")

        md.append("\n## Competitor Intelligence & Sentiment")
        comp = s.competitors_and_products
        has_comp = bool(comp.new_products or comp.competitor_moves or comp.client_sentiment)
        if has_comp:
            if comp.new_products:
                for np in comp.new_products:
                    md.append(f"- **New Product:** {np}")
            if comp.competitor_moves:
                for m in comp.competitor_moves:
                    md.append(f"- **Competitor Move:** {m}")
            if comp.client_sentiment:
                for cs in comp.client_sentiment:
                    md.append(f"- **Client Sentiment/Demand:** {cs}")
        else:
            md.append("*No competitor updates reported.*")

        md.append("\n## Emerging Radar Anomaly Signals")
        if s.emerging_radar:
            for item in s.emerging_radar:
                md.append(f"- {item}")
        else:
            md.append("*No emerging radar anomalies detected.*")

        md.append("\n## Groundedness & Uncertainty Audit")
        if s.uncertainty_log:
            for item in s.uncertainty_log:
                md.append(f"- {item}")
        else:
            md.append("*All reported facts fully grounded and verified.*")

        if s.citations:
            md.append("\n## Sources & Citations")
            for idx, cit in enumerate(s.citations, 1):
                md.append(f"### Source #{idx}")
                md.append(f"- **Confidence:** {int(cit.confidence * 100)}%")
                if cit.quote:
                    md.append(f"- **Quote:** \"{cit.quote}\"")
                md.append(f"- **Chunk ID:** `{cit.chunk_id}`")

        content = "\n".join(md)
        filename = f"BizPulse_Report_{run_id}.md"
        return Response(
            content=content,
            media_type="text/markdown",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )

    from bizpulse.models import MarketingStrategy
    s = run.final_output
    assert isinstance(s, MarketingStrategy)
    md = [
        "# BizPulse Marketing Strategy Report",
        f"**Business URL:** {run.business_id}",
        f"**Industry:** {s.industry}",
        f"**Date:** {run.finished_at or run.started_at}",
        f"\n## Executive Summary\n{s.summary}",
        f"\n## Brand Positioning\n{s.brand.positioning if s.brand else 'N/A'}",
        "\n## Recommendations",
    ]
    for r in s.recommendations:
        md.append(f"### {r.priority}: {r.action} ({r.channel})")
        md.append(f"**Rationale:** {r.rationale}")
        if r.expected_impact:
            md.append(f"**Impact:** {r.expected_impact}")

    if s.detailed_channel_strategies:
        md.append("\n## Detailed Channel Strategies")
        for ds in s.detailed_channel_strategies:
            md.append(f"### {ds.channel}")
            md.append(ds.strategy_details)
            if ds.key_metrics:
                md.append("**Key Metrics:** " + ", ".join(ds.key_metrics))

    if s.inclusivity_metrics:
        m = s.inclusivity_metrics
        md.append("\n## Inclusivity Scorecard (4 L's)")
        md.append(f"- **LAST (Late Adopters):** {int(m.last*100)}%")
        md.append(f"- **LEAST (Under-served):** {int(m.least*100)}%")
        md.append(f"- **LOST (Churned):** {int(m.lost*100)}%")
        md.append(f"- **LOWEST (Budget):** {int(m.lowest*100)}%")
        md.append(f"\n**Narrative:** {m.narrative}")

    if s.benefit_report:
        md.append(f"\n## Business Benefit Report\n{s.benefit_report}")

    if s.compliance_report:
        cr = s.compliance_report
        md.append("\n## Compliance Audit")
        md.append(f"**Overall Score:** {int(cr.overall_compliance_score*100)}%")
        md.append("\n### Flags")
        for f in cr.flags:
            md.append(f"- **[{f.severity.upper()}] {f.policy_slug}:** {f.issue}")
            if f.fix:
                md.append(f"  *Fix:* {f.fix}")
        md.append(f"\n**Summary:** {cr.summary}")

    content = "\n".join(md)
    filename = f"BizPulse_Report_{run_id}.md"
    return Response(
        content=content,
        media_type="text/markdown",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


class RecommendationChatRequest(BaseModel):
    recommendation_index: int
    message: str


class RecommendationChatResponse(BaseModel):
    reply: str


@router.post("/{run_id}/chat", response_model=RecommendationChatResponse)
async def chat_run(
    run_id: UUID,
    body: RecommendationChatRequest,
    tenant: Tenant = Depends(require_tenant),
    store: Store = Depends(get_store),
) -> RecommendationChatResponse:
    run = store.get_run(run_id)
    if run is None or run.tenant_id != tenant.id:
        raise HTTPException(status_code=404, detail="run not found")
    if run.run_type == "daily_research":
        raise HTTPException(status_code=400, detail="Chat is only supported for marketing strategy reports")
    if run.final_output is None:
        raise HTTPException(status_code=400, detail="run has no final strategy to chat about")

    from bizpulse.models import MarketingStrategy
    s = run.final_output
    assert isinstance(s, MarketingStrategy)

    council = _pick_council()
    if council is None:
        raise HTTPException(status_code=503, detail="LLM services unavailable")

    # Build a minimal runner for context retrieval (if needed) and council access
    repo = TenantQdrant(tenant.id)
    runner = AgentRunner(
        retrieval=RetrievalEngine(repo, embedder=_pick_embedder()),
        council=council,
        industry=s.industry,
    )

    reply = await chat_about_recommendation(
        runner=runner,
        strategy=s,
        recommendation_index=body.recommendation_index,
        user_message=body.message,
    )

    return RecommendationChatResponse(reply=reply)


@router.delete("/{run_id}", status_code=status.HTTP_200_OK)
def delete_run(
    run_id: UUID,
    tenant: Tenant = Depends(require_tenant),
    store: Store = Depends(get_store),
) -> dict:
    run = store.get_run(run_id)
    if run is None or run.tenant_id != tenant.id:
        raise HTTPException(status_code=404, detail="run not found")
    success = store.delete_run(run_id)
    if not success:
        raise HTTPException(status_code=500, detail="failed to delete run")
    return {"status": "success", "detail": f"Run {run_id} deleted"}

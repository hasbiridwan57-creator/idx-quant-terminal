from pathlib import Path
from typing import Optional, Tuple
from jinja2 import Environment, FileSystemLoader
from app.services.dupont_engine import DuPontAnalysisBundle
from app.services.llm_analyzer import LLMAnomalySummary

def render_dupont_report_export(
    bundle: DuPontAnalysisBundle,
    anomaly: LLMAnomalySummary,
    template_dir: Optional[str] = None,
) -> Tuple[bytes, str, str]:
    """PDF bila WeasyPrint tersedia, jika tidak fallback ke print-ready HTML."""
    if template_dir is None:
        template_dir = str(Path(__file__).resolve().parents[1] / "templates")
    env = Environment(loader=FileSystemLoader(template_dir))
    tmpl = env.get_template("pdf_report.html")
    html_str = tmpl.render(bundle=bundle, anomaly=anomaly)

    try:
        from weasyprint import HTML  # type: ignore
        pdf_bytes = HTML(string=html_str).write_pdf()
        filename = f"DuPont_Report_{bundle.current.ticker}_{bundle.current.year}.pdf"
        return pdf_bytes, "application/pdf", filename
    except Exception:
        filename = f"DuPont_Report_{bundle.current.ticker}_{bundle.current.year}_Printable.html"
        return html_str.encode("utf-8"), "text/html; charset=utf-8", filename
# ==============================================================================
# BIBLIOTEKI
# ==============================================================================
import os
import json
import logging
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from dotenv import load_dotenv

from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
# ==============================================================================

# Wczytanie zmiennych środowiskowych z pliku .env
load_dotenv()

# ==============================================================================
# KONFIGURACJA RAPORTU (Pobrana z pliku .env)
# ==============================================================================
PRODUCT_ID = os.environ.get("CENEO_PRODUCT_ID")
REVIEWS_DIR = os.environ.get("SYSTEM_REVIEWS_DIR")
LOGS_DIR = os.environ.get("SYSTEM_LOGS_DIR")
# ==============================================================================

# ==============================================================================
# GŁÓWNY SKRYPT
# ==============================================================================


# Funkcja pomocnicza/konfiguracyjna: Inicjalizuje system logowania i tworzy plik logu dla danego produktu.
def setup_logging(product_id, logs_dir):
    if not logs_dir:
        return
    os.makedirs(logs_dir, exist_ok=True)
    log_file = os.path.join(logs_dir, f"{product_id}.log")

    for handler in logging.root.handlers[:]:
        logging.root.removeHandler(handler)

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] (REPORTER) %(message)s',
        handlers=[
            logging.FileHandler(log_file, mode='a', encoding='utf-8'),
            logging.StreamHandler()
        ]
    )


# Funkcja pomocnicza wejścia-wyjścia (I/O): Wczytuje dane analityczne w formacie JSON dla wybranego typu modelu.
def load_analysis_data(product_id, target_dir, file_type):
    input_filename = f"analysis_review_{file_type}_{product_id}.json"
    input_path = os.path.join(target_dir, input_filename)
    
    if not os.path.exists(input_path):
        logging.error(f"Nie znaleziono pliku analizy sztucznej inteligencji ({file_type}): {input_path}")
        return None
        
    with open(input_path, 'r', encoding='utf-8') as f:
        return json.load(f)


# Funkcja pomocnicza: Łamie zbyt długi string (powyżej 18 znaków lub ze znakiem " + ") na dwa wiersze przy użyciu "\n".
def format_text_wrap(text_str):
    if " + " in text_str:
        parts = text_str.split(" + ", 1)
        return f"{parts[0]} +\n{parts[1]}"
    elif len(text_str) > 18 and " " in text_str:
        mid = len(text_str) // 2
        spaces = [i for i, char in enumerate(text_str) if char == " "]
        closest_space = min(spaces, key=lambda x: abs(x - mid))
        return f"{text_str[:closest_space]}\n{text_str[closest_space+1:]}"
    return text_str


# Funkcja pomocnicza graficzna: Zawija długie etykiety tekstowe na osi Y wykresu oraz w legendzie.
def wrap_labels(ax, legend_title_text=""):
    # 1. Zawijanie etykiet na osi Y (modele)
    y_labels = [tick.get_text() for tick in ax.get_yticklabels()]
    wrapped_y_labels = [format_text_wrap(label) for label in y_labels]
    ax.set_yticklabels(wrapped_y_labels)

    # 2. Zawijanie etykiet w legendzie
    legend = ax.get_legend()
    if legend:
        title = legend.get_title().get_text() if legend.get_title() else legend_title_text
        labels = [text.get_text() for text in legend.get_texts()]
        handles = legend.legend_handles
        
        wrapped_labels = [format_text_wrap(label) for label in labels]
        ax.legend(handles, wrapped_labels, title=title, loc='upper left', bbox_to_anchor=(1.01, 1.0))


# Główna funkcja analityczno-graficzna: Parsuje dane JSON do struktur Pandas DataFrame i generuje 4 wykresy PNG w Matplotlib/Seaborn.
def generate_charts(data, target_dir, file_type):
    plt.close('all')
    sns.set_theme(style="whitegrid")
    
    plt.rcParams.update({'font.size': 9, 'figure.titlesize': 11})
    
    full_reviews_list = []
    sentences_list = []
    aspects_list = []
    
    for model_data in data.get("analysis_results", []):
        model_name = model_data.get("model_name", "unknown")
        for rev in model_data.get("reviews", []):
            rev_num = rev.get("review_number")
            
            fr = rev.get("full_review", {})
            review_sentiment = fr.get("sentiment", "brak")
            
            full_reviews_list.append({
                "model": model_name,
                "review_number": rev_num,
                "sentiment": review_sentiment,
                "emotion": fr.get("emotion", "brak")
            })
            
            for asp in fr.get("aspects", []):
                if isinstance(asp, dict):
                    asp_name = asp.get("name", "nieznany")
                    asp_sentiment = asp.get("sentiment", review_sentiment)
                else:
                    asp_name = asp
                    asp_sentiment = review_sentiment

                aspects_list.append({
                    "model": model_name,
                    "aspect": asp_name,
                    "sentiment": asp_sentiment
                })
                
            for sent in rev.get("sentences", []):
                sentences_list.append({
                    "model": model_name,
                    "review_number": rev_num,
                    "sentence_number": sent.get("sentence_number"),
                    "sentiment": sent.get("sentiment", "brak"),
                    "emotion": sent.get("emotion", "brak")
                })

    df_fr = pd.DataFrame(full_reviews_list)
    df_sent = pd.DataFrame(sentences_list)
    df_asp = pd.DataFrame(aspects_list)
    
    base_palette = {"pozytywny": "#2ecc71", "neutralny": "#95a5a6", "negatywny": "#e74c3c", "brak": "#bdc3c7"}
    palette_sentiment = base_palette.copy()

    all_sentiments = set()
    for df in [df_fr, df_sent, df_asp]:
        if not df.empty and "sentiment" in df.columns:
            all_sentiments.update(df["sentiment"].dropna().unique())

    for sentiment_val in all_sentiments:
        if sentiment_val not in palette_sentiment:
            palette_sentiment[sentiment_val] = "#7f8c8d"
            
    num_models = len(df_fr["model"].unique()) if not df_fr.empty else 1
    
    # Elastyczne dopasowanie wysokości wykresu pod kątem wieloliniowych etykiet osi Y
    h_height = max(3.2, min(6.0, num_models * 0.8 + 1.8))
    
    chart_paths = {}

    # 1. WYKRES: Sentyment Globalny
    fig, ax = plt.subplots(figsize=(10, h_height))
    if not df_fr.empty and "sentiment" in df_fr.columns:
        sns.countplot(data=df_fr, y="model", hue="sentiment", palette=palette_sentiment, ax=ax)
        plt.title("Sentyment Globalny per Model (Całość Recenzji)", pad=12)
        plt.ylabel("Model LLM")
        plt.xlabel("Liczba Recenzji")
        wrap_labels(ax, "Sentyment")
    else:
        plt.text(0.5, 0.5, "Brak danych sentymentu", ha='center', va='center')
    
    p1 = os.path.join(target_dir, f"chart_{file_type}_global_sentiment.png")
    plt.savefig(p1, dpi=200, bbox_inches='tight')
    plt.close()
    chart_paths["global_sentiment"] = p1

    # 2. WYKRES: Sentyment na poziomie zdań
    fig, ax = plt.subplots(figsize=(10, h_height))
    if not df_sent.empty and "sentiment" in df_sent.columns:
        sns.countplot(data=df_sent, y="model", hue="sentiment", palette=palette_sentiment, ax=ax)
        plt.title("Sentyment na Poziomie Pojedynczych Zdań", pad=12)
        plt.ylabel("Model LLM")
        plt.xlabel("Liczba Zdań")
        wrap_labels(ax, "Sentyment")
    else:
        plt.text(0.5, 0.5, "Brak danych dla zdań", ha='center', va='center')
        
    p2 = os.path.join(target_dir, f"chart_{file_type}_sentence_sentiment.png")
    plt.savefig(p2, dpi=200, bbox_inches='tight')
    plt.close()
    chart_paths["sentence_sentiment"] = p2

    # 3. WYKRES: Profil Emocjonalny
    fig, ax = plt.subplots(figsize=(10, 4.5))
    ekman_emotions = ["radość", "smutek", "strach", "złość", "zaskoczenie", "wstręt"]
    
    if not df_fr.empty and "emotion" in df_fr.columns:
        df_fr_filtered = df_fr[df_fr["emotion"].isin(ekman_emotions)]
        sns.countplot(data=df_fr_filtered, y="emotion", hue="model", order=ekman_emotions, ax=ax)
        plt.title("Profil Emocjonalny Produktu (Taksonomia Ekmana)", pad=12)
        plt.xlabel("Liczba Wykryć")
        plt.ylabel("Emocja")
        wrap_labels(ax, "Model")
    else:
        plt.text(0.5, 0.5, "Brak danych emocji", ha='center', va='center')
    
    p3 = os.path.join(target_dir, f"chart_{file_type}_emotions.png")
    plt.savefig(p3, dpi=200, bbox_inches='tight')
    plt.close()
    chart_paths["emotions"] = p3

    # 4. WYKRES: Wykres Aspektów
    fig, ax = plt.subplots(figsize=(10, 4.5))
    if not df_asp.empty and "aspect" in df_asp.columns:
        top_aspects = df_asp["aspect"].value_counts().head(10).index
        df_asp_top = df_asp[df_asp["aspect"].isin(top_aspects)]
        sns.countplot(data=df_asp_top, y="aspect", hue="sentiment", order=top_aspects, palette=palette_sentiment, ax=ax)
        plt.title("Top 10 Aspektów Produktu z podziałem na Sentyment", pad=12)
        plt.xlabel("Liczba Wystąpień")
        plt.ylabel("Aspekt")
        wrap_labels(ax, "Ocena aspektu")
    else:
        plt.text(0.5, 0.5, "Brak aspektów do wyświetlenia", ha='center', va='center')
        plt.title("Top 10 Najczęściej Wykrywanych Aspektów", pad=12)
        
    p4 = os.path.join(target_dir, f"chart_{file_type}_aspects.png")
    plt.savefig(p4, dpi=200, bbox_inches='tight')
    plt.close()
    chart_paths["aspects"] = p4

    return chart_paths, df_fr, df_sent, df_asp


# Funkcja pomocnicza konfiguracyjna: Rejestruje czcionki systemowe TTF w ReportLab dla obsługi polskich znaków (w przypadku braku używa czcionki Helvetica).
def setup_pdf_fonts():
    possible_fonts = [
        ("Arial", "arial.ttf", "arialbd.ttf"),
        ("LiberationSans", "LiberationSans-Regular.ttf", "LiberationSans-Bold.ttf"),
        ("DejaVuSans", "DejaVuSans.ttf", "DejaVuSans-Bold.ttf")
    ]
    for name, reg, bold in possible_fonts:
        try:
            pdfmetrics.registerFont(TTFont(name, reg))
            pdfmetrics.registerFont(TTFont(f"{name}-Bold", bold))
            return name, f"{name}-Bold"
        except Exception:
            continue
    return "Helvetica", "Helvetica-Bold"


# Główna funkcja raportująca: Składa i kompiluje dokument PDF z tabelami statystycznymi oraz osadzonymi wykresami za pomocą ReportLab Platypus.
def build_pdf_report(data, chart_paths, df_fr, df_sent, df_asp, product_id, target_dir, file_type):
    pdf_path = os.path.join(target_dir, f"report_{file_type}_{product_id}.pdf")
    doc = SimpleDocTemplate(pdf_path, pagesize=letter, leftMargin=35, rightMargin=35, topMargin=40, bottomMargin=40)
    
    font_reg, font_bold = setup_pdf_fonts()
    styles = getSampleStyleSheet()
    
    title_style = ParagraphStyle('RepTitle', parent=styles['Heading1'], fontName=font_bold, fontSize=18, leading=22, textColor=colors.HexColor('#2c3e50'), spaceAfter=15)
    h2_style = ParagraphStyle('RepH2', parent=styles['Heading2'], fontName=font_bold, fontSize=13, leading=17, textColor=colors.HexColor('#2980b9'), spaceBefore=18, spaceAfter=10)
    body_style = ParagraphStyle('RepBody', parent=styles['Normal'], fontName=font_reg, fontSize=10, leading=14, textColor=colors.HexColor('#333333'))
    meta_style = ParagraphStyle('RepMeta', parent=styles['Normal'], fontName=font_reg, fontSize=9, leading=12, textColor=colors.HexColor('#7f8c8d'), spaceAfter=15)
    
    table_cell_style = ParagraphStyle('TableCell', parent=styles['Normal'], fontName=font_reg, fontSize=9, leading=12, alignment=1)
    table_header_style = ParagraphStyle('TableHeader', parent=styles['Normal'], fontName=font_bold, fontSize=9, leading=12, textColor=colors.whitesmoke, alignment=1)
    
    table_cell_left_bold = ParagraphStyle('TableCellLeftBold', parent=styles['Normal'], fontName=font_bold, fontSize=9, leading=12, alignment=0)
    table_cell_left = ParagraphStyle('TableCellLeft', parent=styles['Normal'], fontName=font_reg, fontSize=8, leading=11, alignment=0, textColor=colors.HexColor('#555555'))

    story = []

    story.append(Paragraph(f"Raport Analizy Opinii ({file_type.upper()}): {data.get('product_title', 'Brak Tytułu')}", title_style))
    story.append(Paragraph(f"<b>ID Produktu:</b> {product_id} | <b>Plik źródłowy:</b> analysis_review_{file_type}_{product_id}.json", meta_style))
    story.append(Spacer(1, 10))

    story.append(Paragraph("1. Podsumowanie Wykonawcze (Executive Summary)", h2_style))
    total_revs = len(df_fr['review_number'].unique()) if not df_fr.empty else 0
    summary_text = f"Niniejszy raport zawiera porównawczą analizę sentymentu, aspektów (ABSA) oraz emocji dla wybranego produktu (typ analizy: {file_type}). W procesie ewaluacji uwzględniono {total_revs} unikalnych opinii konsumenckich z platformy Ceneo."
    story.append(Paragraph(summary_text, body_style))
    story.append(Spacer(1, 15))

    story.append(Paragraph("2. Analiza Sentymentu Globalnego oraz Poziomu Zdań", h2_style))
    story.append(Spacer(1, 5))
    
    num_models = len(df_fr["model"].unique()) if not df_fr.empty else 1
    calc_height = max(160, min(260, num_models * 35 + 80))
    
    img_global = Image(chart_paths["global_sentiment"], width=500, height=calc_height)
    img_sentence = Image(chart_paths["sentence_sentiment"], width=500, height=calc_height)
    
    story.append(Paragraph("<b>Globalna Polaryzacja Opinii (Całe Wypowiedzi):</b>", body_style))
    story.append(Spacer(1, 5))
    story.append(img_global)
    story.append(Spacer(1, 15))
    
    story.append(Paragraph("<b>Polaryzacja Opinii na Poziomie Pojedynczych Zdań:</b>", body_style))
    story.append(Spacer(1, 5))
    story.append(img_sentence)
    story.append(Spacer(1, 15))

    story.append(Paragraph("3. Profil Emocjonalny oraz Sentyment Kluczowych Aspektów", h2_style))
    story.append(Spacer(1, 5))
    
    img_emotions = Image(chart_paths["emotions"], width=500, height=220)
    img_aspects = Image(chart_paths["aspects"], width=500, height=220)
    
    story.append(Paragraph("<b>Profil Emocjonalny Produktu:</b>", body_style))
    story.append(Spacer(1, 5))
    story.append(img_emotions)
    story.append(Spacer(1, 15))
    
    story.append(Paragraph("<b>Sentyment Kluczowych Aspektów (Top 10):</b>", body_style))
    story.append(Spacer(1, 5))
    story.append(img_aspects)
    story.append(Spacer(1, 15))

    col_widths_ab = [182, 90, 90, 90, 90] 
    style_table_ab = TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#2c3e50')),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#e2e8f0')),
        ('BACKGROUND', (0,1), (-1,-1), colors.HexColor('#f8f9fa')),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4), ('TOPPADDING', (0,0), (-1,-1), 4),
    ])

    headers_ab = [
        Paragraph("Nazwa Modelu", table_header_style), 
        Paragraph("Pozytywny", table_header_style), 
        Paragraph("Neutralny", table_header_style), 
        Paragraph("Negatywny", table_header_style), 
        Paragraph("Brak", table_header_style)
    ]

    story.append(Paragraph("4. Statystyczne Zestawienie Porównawcze", h2_style))
    
    story.append(Paragraph("<b>Tabela 4A: Sentyment na poziomie CAŁYCH OPINII (Globalny)</b>", body_style))
    story.append(Spacer(1, 4))
    table_data_a = [headers_ab]
    if not df_fr.empty and 'model' in df_fr.columns:
        for model_name in df_fr['model'].unique():
            sub_df = df_fr[df_fr['model'] == model_name]
            table_data_a.append([
                Paragraph(model_name, table_cell_style),
                Paragraph(str(len(sub_df[sub_df['sentiment'] == 'pozytywny'])), table_cell_style),
                Paragraph(str(len(sub_df[sub_df['sentiment'] == 'neutralny'])), table_cell_style),
                Paragraph(str(len(sub_df[sub_df['sentiment'] == 'negatywny'])), table_cell_style),
                Paragraph(str(len(sub_df[sub_df['sentiment'] == 'brak'])), table_cell_style)
            ])
    table_a = Table(table_data_a, colWidths=col_widths_ab)
    table_a.setStyle(style_table_ab)
    story.append(table_a)
    story.append(Spacer(1, 12))

    story.append(Paragraph("<b>Tabela 4B: Sentyment na poziomie POJEDYNCZYCH ZDAŃ</b>", body_style))
    story.append(Spacer(1, 4))
    table_data_b = [headers_ab]
    if not df_sent.empty and 'model' in df_sent.columns:
        for model_name in df_sent['model'].unique():
            sub_df = df_sent[df_sent['model'] == model_name]
            table_data_b.append([
                Paragraph(model_name, table_cell_style),
                Paragraph(str(len(sub_df[sub_df['sentiment'] == 'pozytywny'])), table_cell_style),
                Paragraph(str(len(sub_df[sub_df['sentiment'] == 'neutralny'])), table_cell_style),
                Paragraph(str(len(sub_df[sub_df['sentiment'] == 'negatywny'])), table_cell_style),
                Paragraph(str(len(sub_df[sub_df['sentiment'] == 'brak'])), table_cell_style)
            ])
    table_b = Table(table_data_b, colWidths=col_widths_ab)
    table_b.setStyle(style_table_ab)
    story.append(table_b)
    story.append(Spacer(1, 12))

    story.append(Paragraph("<b>Tabela 4C: Szczegółowa ocena polaryzacji Top 10 aspektów w rozbiciu na modele LLM</b>", body_style))
    story.append(Spacer(1, 4))
    
    headers_c = [
        Paragraph("Nazwa Aspektu / Cechy", table_header_style), 
        Paragraph("Model Oceniający", table_header_style), 
        Paragraph("Pozytywne (Zaleta)", table_header_style), 
        Paragraph("Neutralne", table_header_style),  
        Paragraph("Negatywne (Wada)", table_header_style)
    ]
    table_data_c = [headers_c]
    style_table_c_ops = [
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#2c3e50')),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#e2e8f0')),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ('TOPPADDING', (0,0), (-1,-1), 4),
    ]
    
    current_row = 1
    if not df_asp.empty and "aspect" in df_asp.columns:
        top_10_names = df_asp["aspect"].value_counts().head(10).index
        unique_models = df_asp["model"].unique()
        
        for aspect_name in top_10_names:
            start_aspect_row = current_row
            
            for idx, model_name in enumerate(unique_models):
                sub_asp_model = df_asp[(df_asp["aspect"] == aspect_name) & (df_asp["model"] == model_name)]
                
                pos_c = len(sub_asp_model[sub_asp_model["sentiment"] == "pozytywny"])
                neu_c = len(sub_asp_model[sub_asp_model["sentiment"] == "neutralny"])
                neg_c = len(sub_asp_model[sub_asp_model["sentiment"] == "negatywny"])
                
                asp_cell_text = Paragraph(f"<b>{aspect_name}</b>", table_cell_left_bold) if idx == 0 else Paragraph("", table_cell_left_bold)
                
                table_data_c.append([
                    asp_cell_text,
                    Paragraph(model_name, table_cell_left),
                    Paragraph(f"<font color='#2ecc71'><b>{pos_c}</b></font>" if pos_c > 0 else "0", table_cell_style),
                    Paragraph(str(neu_c), table_cell_style),
                    Paragraph(f"<font color='#e74c3c'><b>{neg_c}</b></font>" if neg_c > 0 else "0", table_cell_style)
                ])
                current_row += 1
            
            end_aspect_row = current_row - 1
            style_table_c_ops.append(('SPAN', (0, start_aspect_row), (0, end_aspect_row)))
            style_table_c_ops.append(('BACKGROUND', (0, start_aspect_row), (0, end_aspect_row), colors.HexColor('#f1f2f6')))
            style_table_c_ops.append(('LINEBELOW', (0, end_aspect_row), (-1, end_aspect_row), 1.5, colors.HexColor('#a4b0be')))
            
    table_c = Table(table_data_c, colWidths=[140, 162, 80, 80, 80])
    table_c.setStyle(TableStyle(style_table_c_ops))
    story.append(table_c)
    story.append(Spacer(1, 15))

    story.append(Paragraph("5. Podsumowanie modeli", h2_style))
    story.append(Spacer(1, 5))
    metrics_table_data = [[Paragraph("Nazwa Modelu", table_header_style), Paragraph("Suma Ocenionych", table_header_style), Paragraph("Pozytywny (Pos)", table_header_style), Paragraph("Neutralny (Neu)", table_header_style), Paragraph("Negatywny (Neg)", table_header_style)]]

    for model_data in data.get("analysis_results", []):
        m_name = model_data.get("model_name", "unknown")
        metrics = model_data.get("metrics", {})
        breakdown = metrics.get("sentiment_breakdown", {})
        metrics_table_data.append([
            Paragraph(m_name, table_cell_style),
            Paragraph(str(metrics.get("total_reviews_evaluated", 0)), table_cell_style),
            Paragraph(str(breakdown.get("positive", 0)), table_cell_style),
            Paragraph(str(breakdown.get("neutral", 0)), table_cell_style),
            Paragraph(str(breakdown.get("negative", 0)), table_cell_style)
        ])

    metrics_table = Table(metrics_table_data, colWidths=[182, 90, 90, 90, 90])
    metrics_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#273c75')),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#dcdde1')),
        ('BACKGROUND', (0,1), (-1,-1), colors.HexColor('#f5f6fa')),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4), ('TOPPADDING', (0,0), (-1,-1), 4),
    ]))
    story.append(metrics_table)

    doc.build(story)
    logging.info(f"[SUKCES] Dokument PDF wygenerowany i zapisany pomyślnie w: {pdf_path}")


# Główna funkcja sterująca (Controller): Koordynuje pętlę generowania wykresów i PDF-ów osobno dla typów 'encoder' oraz 'decoder', a następnie usuwa tymczasowe obrazy PNG.
def generate_product_report(product_id):
    if not product_id or not REVIEWS_DIR or not LOGS_DIR:
        print("BŁĄD: Brak wymaganych zmiennych (CENEO_PRODUCT_ID, SYSTEM_REVIEWS_DIR, SYSTEM_LOGS_DIR) w pliku .env!")
        return

    setup_logging(product_id, LOGS_DIR)
    
    target_dir = os.path.join(REVIEWS_DIR, product_id)
    if not os.path.exists(target_dir):
        logging.error(f"Katalog produktu nie istnieje: {target_dir}")
        return

    for file_type in ["encoder", "decoder"]:
        logging.info("==============================================================================")
        logging.info(f"Rozpoczynam proces generowania raportu PDF dla produktu ID: {product_id} ({file_type})")

        data = load_analysis_data(product_id, target_dir, file_type)
        if not data:
            logging.warning(f"Pomijanie generowania raportu dla typu '{file_type}' z powodu braku pliku źródłowego.")
            continue
            
        logging.info(f"Trwa matematyczna agregacja danych i generowanie wykresów w Matplotlib dla {file_type}...")
        chart_paths, df_fr, df_sent, df_asp = generate_charts(data, target_dir, file_type)
        
        logging.info(f"Kompilowanie raportu biznesowego (ReportLab Platypus) dla {file_type}...")
        build_pdf_report(data, chart_paths, df_fr, df_sent, df_asp, product_id, target_dir, file_type)
        
        logging.info(f"Czyszczenie tymczasowych plików wykresów dla {file_type}...")
        for path in chart_paths.values():
            try:
                if os.path.exists(path):
                    os.remove(path)
            except Exception as e:
                logging.warning(f"Nie udało się usunąć pliku tymczasowego {path}: {e}")

        logging.info(f"Proces generowania raportu dla {file_type} zakończony powodzeniem.")
        logging.info("==============================================================================\n")

if __name__ == "__main__":
    generate_product_report(PRODUCT_ID)
"""
Receipt PDF Template System
Similar to Jinja2/Django templates but for PDF generation
"""

from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from io import BytesIO
import datetime
import os
import requests
from typing import Dict, Any, Optional


class ReceiptTemplate:
    """Professional receipt template with customizable branding and layout"""
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize template with configuration
        
        Args:
            config: Template configuration dict with keys:
                - company_name: Company name for header
                - company_tagline: Company tagline/subtitle
                - logo_path: Path to company logo (optional)
                - primary_color: Primary brand color
                - secondary_color: Secondary brand color
                - contact_email: Contact email for footer
                - page_size: Page size (A4, letter, etc.)
        """
        self.config = config or {}
        self.styles = self._create_styles()
    
    def _create_styles(self) -> Dict[str, ParagraphStyle]:
        """Create custom paragraph styles based on configuration"""
        base_styles = getSampleStyleSheet()
        
        # Get colors from config or use defaults
        primary_color = self.config.get('primary_color', colors.darkblue)
        secondary_color = self.config.get('secondary_color', colors.grey)
        
        return {
            'company_name': ParagraphStyle(
                'CompanyName',
                parent=base_styles['Heading2'],
                fontSize=18,
                spaceAfter=10,
                alignment=TA_CENTER,
                textColor=primary_color,
                fontName='Helvetica-Bold'
            ),
            'company_tagline': ParagraphStyle(
                'CompanyTagline',
                parent=base_styles['Heading3'],
                fontSize=14,
                spaceAfter=15,
                alignment=TA_CENTER,
                textColor=secondary_color,
                fontName='Helvetica'
            ),
            'receipt_title': ParagraphStyle(
                'ReceiptTitle',
                parent=base_styles['Heading1'],
                fontSize=24,
                spaceAfter=20,
                alignment=TA_CENTER,
                textColor=primary_color,
                fontName='Helvetica-Bold'
            ),
            'receipt_number': ParagraphStyle(
                'ReceiptNumber',
                parent=base_styles['Normal'],
                fontSize=12,
                spaceAfter=5,
                alignment=TA_RIGHT,
                textColor=colors.black,
                fontName='Helvetica-Bold'
            ),
            'footer': ParagraphStyle(
                'Footer',
                parent=base_styles['Normal'],
                fontSize=10,
                spaceAfter=5,
                alignment=TA_CENTER,
                textColor=secondary_color,
                fontName='Helvetica'
            )
        }
    
    def _create_header(self) -> list:
        """Create header section with company branding and logo"""
        story = []
        
        # Try to load logo from webapp URL
        logo_image = self._load_logo_from_webapp()
        if logo_image:
            story.append(logo_image)
            story.append(Spacer(1, 10))
        
        # Company name and tagline
        company_name = self.config.get('company_name', 'Welcomepage')
        company_tagline = self.config.get('company_tagline', '')
        
        # Only show tagline if company name is not "Welcomepage" (to avoid redundancy with logo)
        if company_name.lower() != 'welcomepage':
            story.append(Paragraph(company_name, self.styles['company_name']))
        
        # Only show tagline if it's not empty and not the default
        if company_tagline and company_tagline != 'Professional Welcome Pages':
            story.append(Paragraph(company_tagline, self.styles['company_tagline']))
        story.append(Spacer(1, 20))
        
        return story
    
    def _load_logo_from_webapp(self) -> Optional[Image]:
        """
        Load logo from webapp URL (WEBAPP_URL/welcomepage-logo.png)
        Similar to how other parts of the codebase use WEBAPP_URL
        """
        try:
            # Get webapp URL from environment (same pattern as other files)
            webapp_url = os.getenv('WEBAPP_URL')
            if not webapp_url:
                return None
            
            # Construct logo URL
            logo_url = f"{webapp_url}/welcomepage-logo.png"
            
            # Fetch logo from webapp
            response = requests.get(logo_url, timeout=5)
            response.raise_for_status()
            
            # Create Image object from response content
            logo_buffer = BytesIO(response.content)
            
            # Calculate proper aspect ratio based on natural dimensions (720 × 119)
            # Natural aspect ratio: 720/119 ≈ 6.05
            # Set width to 3 inches and calculate height to maintain aspect ratio
            logo_width = 3 * inch
            logo_height = logo_width * (119 / 720)  # Maintain aspect ratio
            
            logo_image = Image(logo_buffer, width=logo_width, height=logo_height)
            
            return logo_image
            
        except Exception as e:
            # If logo loading fails, continue without it
            # This ensures the PDF generation doesn't fail if logo is unavailable
            print(f"Warning: Could not load logo from {webapp_url}/welcomepage-logo.png: {e}")
            return None
    
    def _format_payment_method(self, payment_data: Dict[str, Any]) -> str:
        """
        Format payment method information
        Try to get last 4 digits from Stripe payment method if available
        """
        try:
            # Try to get payment method details from Stripe
            import stripe
            
            # Get the payment intent to access payment method details
            payment_intent_id = payment_data.get('id')
            if payment_intent_id:
                payment_intent = stripe.PaymentIntent.retrieve(payment_intent_id)
                
                # Get the payment method
                if payment_intent.payment_method:
                    payment_method = stripe.PaymentMethod.retrieve(payment_intent.payment_method)
                    
                    # Get card details
                    if payment_method.card:
                        last4 = payment_method.card.last4
                        brand = payment_method.card.brand.title()
                        return f"{brand} •••• {last4}"
            
            # Fallback if we can't get card details
            return "Card ending in ••••"
            
        except Exception as e:
            # If anything fails, return generic card info
            print(f"Warning: Could not get payment method details: {e}")
            return "Card ending in ••••"
    
    def _create_receipt_table(self, payment_data: Dict[str, Any]) -> Table:
        """Create the main receipt table with transaction details"""
        receipt_data = [
            ['Description', 'Amount'],
        ]
        
        # Add main transaction
        description = payment_data.get('description', 'Welcomepage creation')
        amount = f"${payment_data.get('amount', 0) / 100:.2f} {payment_data.get('currency', 'USD').upper()}"
        receipt_data.append([description, amount])
        
        # Add transaction details (no blank rows, no "Created for")
        receipt_data.extend([
            ['Transaction Date:', payment_data.get('formatted_date', '')],
            ['Payment Method:', self._format_payment_method(payment_data)],
        ])
        
        # Create table with styling
        table = Table(receipt_data, colWidths=[4*inch, 2*inch])
        primary_color = self.config.get('primary_color', colors.darkblue)
        
        table.setStyle(TableStyle([
            # Header row
            ('BACKGROUND', (0, 0), (-1, 0), primary_color),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 12),
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            
            # Data rows
            ('BACKGROUND', (0, 1), (-1, -1), colors.white),
            ('TEXTCOLOR', (0, 1), (-1, -1), colors.black),
            ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 1), (-1, -1), 10),
            ('ALIGN', (0, 1), (0, -1), 'LEFT'),
            ('ALIGN', (1, 1), (1, -1), 'RIGHT'),
            ('BOTTOMPADDING', (0, 1), (-1, -1), 8),
            ('TOPPADDING', (0, 1), (-1, -1), 8),
            
            # Grid lines
            ('GRID', (0, 0), (-1, -1), 0.5, colors.lightgrey),
        ]))
        
        return table
    
    def _create_footer(self) -> list:
        """Create footer section with contact information"""
        story = []
        
        contact_email = self.config.get('contact_email', 'support@welcomepage.com')
        
        story.append(Paragraph("Thank you for your business!", self.styles['footer']))
        story.append(Paragraph(f"Questions? Contact us at {contact_email}", self.styles['footer']))
        story.append(Spacer(1, 20))
        # Removed "Receipt generated on..." line - receipt number is sufficient identification
        
        return story
    
    def generate_pdf(self, payment_data: Dict[str, Any]) -> bytes:
        """
        Generate PDF receipt from payment data
        
        Args:
            payment_data: Dictionary containing:
                - id: Payment intent ID
                - amount: Amount in cents
                - currency: Currency code
                - description: Payment description
                - status: Payment status
                - created: Timestamp
                - metadata: Additional metadata dict
                
        Returns:
            PDF content as bytes
        """
        # Prepare payment data
        formatted_data = {
            **payment_data,
            'formatted_date': datetime.datetime.fromtimestamp(payment_data['created']).strftime('%B %d, %Y at %I:%M %p')
        }
        
        # Create PDF document
        page_size = self.config.get('page_size', A4)
        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=page_size, topMargin=1*inch, bottomMargin=1*inch)
        
        # Build PDF content
        story = []
        
        # Add header
        story.extend(self._create_header())
        
        # Add receipt number (no title needed - receipt number is sufficient)
        receipt_id = f"PI-{payment_data['id'][-8:]}"
        story.append(Paragraph(f"Receipt #: {receipt_id}", self.styles['receipt_number']))
        story.append(Spacer(1, 20))
        
        # Add receipt table
        story.append(self._create_receipt_table(formatted_data))
        story.append(Spacer(1, 40))
        
        # Add footer
        story.extend(self._create_footer())
        
        # Build PDF
        doc.build(story)
        buffer.seek(0)
        
        return buffer.getvalue()


# Template configurations for different use cases
DEFAULT_CONFIG = {
    'company_name': 'Welcomepage',
    'company_tagline': 'Professional Welcome Pages',
    'primary_color': colors.darkblue,
    'secondary_color': colors.grey,
    'contact_email': 'support@welcomepage.com',
    'page_size': A4
}

ENTERPRISE_CONFIG = {
    'company_name': 'Welcomepage Enterprise',
    'company_tagline': 'Enterprise Welcome Page Solutions',
    'primary_color': colors.darkgreen,
    'secondary_color': colors.darkgrey,
    'contact_email': 'enterprise@welcomepage.com',
    'page_size': A4
}

MINIMAL_CONFIG = {
    'company_name': 'Welcomepage',
    'company_tagline': '',
    'primary_color': colors.black,
    'secondary_color': colors.grey,
    'contact_email': 'support@welcomepage.com',
    'page_size': A4
}

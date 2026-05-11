"""
Daily StockSight Report Generator
Generates consolidated reports for Breakout Momentum, Buy Hold Avoid, and StockSight
for Nifty 500 universe and sends via email to subscribers.
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import yfinance as yf
from screener import screen_stocks, UNIVERSES
from signals import scan_breakout_momentum
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os
from typing import List, Dict, Any
import warnings
warnings.filterwarnings("ignore")


class DailyReportGenerator:
    """Generates daily consolidated stock reports for email distribution."""

    def __init__(self):
        self.universe = "Nifty 500 (NSE)"
        self.today = datetime.now()
        self.report_date = self.today.strftime("%Y-%m-%d")

    def run_breakout_momentum_scan(self) -> pd.DataFrame:
        """Run Breakout Momentum strategy scan."""
        try:
            results = scan_breakout_momentum(
                universe=self.universe,
                pe_max=50.0,
                vol_min=3.0,
                rsi_min=50,
                rsi_max=65,
                progress_cb=None
            )

            if results:
                df = pd.DataFrame([{
                    'Ticker': r.ticker,
                    'Price': r.price,
                    'PE': r.pe,
                    'Volume_Ratio': r.vol_ratio,
                    'RSI': r.rsi,
                    'Confidence': r.confidence,
                    'Strategy': 'Breakout Momentum'
                } for r in results])
                return df
            return pd.DataFrame()
        except Exception as e:
            print(f"Error in Breakout Momentum scan: {e}")
            return pd.DataFrame()

    def run_buy_hold_avoid_scan(self) -> pd.DataFrame:
        """Run Buy Hold Avoid composite score scan."""
        try:
            df = screen_stocks(
                universe_name=self.universe,
                pe_threshold=400.0,
                vol_multiplier=0.0,
                rsi_min=0.0,
                progress_callback=None
            )

            if not df.empty:
                df = df.copy()
                df['Action'] = df['Score'].apply(
                    lambda score: "Strong Buy" if score >= 80 else
                                  "Buy / Watch" if score >= 60 else
                                  "Neutral / Wait" if score >= 40 else
                                  "Avoid"
                )
                df['Strategy'] = 'Buy Hold Avoid'
                return df[['Ticker', 'Price', 'PE Ratio', 'Volume Ratio', 'RSI', 'Score', 'Action', 'Strategy']]
            return pd.DataFrame()
        except Exception as e:
            print(f"Error in Buy Hold Avoid scan: {e}")
            return pd.DataFrame()

    def run_stocksight_scan(self) -> pd.DataFrame:
        """Run StockSight main screener scan."""
        try:
            df = screen_stocks(
                universe_name=self.universe,
                pe_threshold=30.0,
                vol_multiplier=1.5,
                rsi_min=50.0,
                progress_callback=None
            )

            if not df.empty:
                df = df.copy()
                df['Strategy'] = 'StockSight Screener'
                return df[['Ticker', 'Price', 'PE Ratio', 'Volume Ratio', 'RSI', 'Score', 'Strategy']]
            return pd.DataFrame()
        except Exception as e:
            print(f"Error in StockSight scan: {e}")
            return pd.DataFrame()

    def generate_consolidated_report(self) -> Dict[str, Any]:
        """Generate consolidated report from all scans."""
        print("Running Breakout Momentum scan...")
        bm_df = self.run_breakout_momentum_scan()

        print("Running Buy Hold Avoid scan...")
        bha_df = self.run_buy_hold_avoid_scan()

        print("Running StockSight scan...")
        ss_df = self.run_stocksight_scan()

        # Combine all results
        all_results = []
        if not bm_df.empty:
            all_results.append(bm_df)
        if not bha_df.empty:
            all_results.append(bha_df)
        if not ss_df.empty:
            all_results.append(ss_df)

        if not all_results:
            return {
                'success': False,
                'message': 'No results generated from any scan',
                'data': None
            }

        combined_df = pd.concat(all_results, ignore_index=True)

        # Remove duplicates (same ticker from multiple strategies)
        combined_df = combined_df.drop_duplicates(subset=['Ticker'], keep='first')

        # Sort by Score descending
        if 'Score' in combined_df.columns:
            combined_df = combined_df.sort_values('Score', ascending=False)

        # Calculate summary statistics
        summary = {
            'total_stocks_scanned': len(UNIVERSES[self.universe]),
            'breakout_momentum_count': len(bm_df),
            'buy_hold_avoid_count': len(bha_df),
            'stocksight_count': len(ss_df),
            'total_unique_stocks': len(combined_df),
            'avg_score': combined_df['Score'].mean() if 'Score' in combined_df.columns else 0,
            'top_performer': combined_df.iloc[0]['Ticker'] if len(combined_df) > 0 else 'N/A'
        }

        return {
            'success': True,
            'data': combined_df,
            'summary': summary,
            'breakout_momentum': bm_df,
            'buy_hold_avoid': bha_df,
            'stocksight': ss_df
        }

    def generate_html_report(self, report_data: Dict[str, Any]) -> str:
        """Generate HTML email report."""
        if not report_data['success']:
            return f"""
            <html>
            <body style="font-family: Arial, sans-serif; max-width: 800px; margin: 0 auto;">
                <h1 style="color: #ff4d4d;">StockSight Daily Report - {self.report_date}</h1>
                <p style="color: #666;">{report_data['message']}</p>
                <p>Please check the application logs for more details.</p>
            </body>
            </html>
            """

        data = report_data['data']
        summary = report_data['summary']

        # Top 10 stocks table
        top_10_html = ""
        if len(data) > 0:
            top_10 = data.head(10)
            top_10_html = """
            <table style="width: 100%; border-collapse: collapse; margin: 20px 0;">
                <thead>
                    <tr style="background-color: #f8f9fa;">
                        <th style="border: 1px solid #ddd; padding: 8px; text-align: left;">Rank</th>
                        <th style="border: 1px solid #ddd; padding: 8px; text-align: left;">Ticker</th>
                        <th style="border: 1px solid #ddd; padding: 8px; text-align: right;">Price</th>
                        <th style="border: 1px solid #ddd; padding: 8px; text-align: right;">PE</th>
                        <th style="border: 1px solid #ddd; padding: 8px; text-align: right;">Volume</th>
                        <th style="border: 1px solid #ddd; padding: 8px; text-align: right;">RSI</th>
                        <th style="border: 1px solid #ddd; padding: 8px; text-align: right;">Score</th>
                        <th style="border: 1px solid #ddd; padding: 8px; text-align: left;">Strategy</th>
                    </tr>
                </thead>
                <tbody>
            """

            for idx, row in top_10.iterrows():
                top_10_html += f"""
                    <tr>
                        <td style="border: 1px solid #ddd; padding: 8px;">{idx + 1}</td>
                        <td style="border: 1px solid #ddd; padding: 8px; font-weight: bold;">{row['Ticker']}</td>
                        <td style="border: 1px solid #ddd; padding: 8px; text-align: right;">₹{row['Price']:.2f}</td>
                        <td style="border: 1px solid #ddd; padding: 8px; text-align: right;">{row.get('PE Ratio', row.get('PE', 'N/A')):.1f}</td>
                        <td style="border: 1px solid #ddd; padding: 8px; text-align: right;">{row['Volume_Ratio']:.2f}x</td>
                        <td style="border: 1px solid #ddd; padding: 8px; text-align: right;">{row['RSI']:.1f}</td>
                        <td style="border: 1px solid #ddd; padding: 8px; text-align: right;">{row.get('Score', 'N/A'):.1f}</td>
                        <td style="border: 1px solid #ddd; padding: 8px;">{row['Strategy']}</td>
                    </tr>
                """

            top_10_html += "</tbody></table>"

        html = f"""
        <html>
        <head>
            <style>
                body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; max-width: 800px; margin: 0 auto; background-color: #f8f9fa; }}
                .header {{ background: linear-gradient(135deg, #25d366, #1aa34b); color: white; padding: 30px; text-align: center; border-radius: 10px 10px 0 0; }}
                .content {{ background: white; padding: 30px; border-radius: 0 0 10px 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
                .metric-card {{ background: #f8f9fa; border: 1px solid #e9ecef; border-radius: 8px; padding: 15px; margin: 10px 0; text-align: center; }}
                .metric-value {{ font-size: 24px; font-weight: bold; color: #25d366; }}
                .metric-label {{ font-size: 14px; color: #6c757d; margin-top: 5px; }}
                .section {{ margin: 30px 0; }}
                .section h2 {{ color: #495057; border-bottom: 2px solid #25d366; padding-bottom: 10px; }}
                table {{ width: 100%; border-collapse: collapse; margin: 20px 0; }}
                th, td {{ border: 1px solid #ddd; padding: 12px; text-align: left; }}
                th {{ background-color: #f8f9fa; font-weight: bold; }}
                .footer {{ text-align: center; margin-top: 30px; padding: 20px; background: #f8f9fa; border-radius: 8px; color: #6c757d; }}
            </style>
        </head>
        <body>
            <div class="header">
                <h1>📈 StockSight Daily Report</h1>
                <p>{self.report_date} | Nifty 500 Universe Analysis</p>
            </div>

            <div class="content">
                <div class="section">
                    <h2>📊 Summary Statistics</h2>
                    <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px;">
                        <div class="metric-card">
                            <div class="metric-value">{summary['total_stocks_scanned']}</div>
                            <div class="metric-label">Stocks Scanned</div>
                        </div>
                        <div class="metric-card">
                            <div class="metric-value">{summary['total_unique_stocks']}</div>
                            <div class="metric-label">Qualified Stocks</div>
                        </div>
                        <div class="metric-card">
                            <div class="metric-value">{summary['avg_score']:.1f}</div>
                            <div class="metric-label">Average Score</div>
                        </div>
                        <div class="metric-card">
                            <div class="metric-value">{summary['top_performer']}</div>
                            <div class="metric-label">Top Performer</div>
                        </div>
                    </div>
                </div>

                <div class="section">
                    <h2>🎯 Strategy Performance</h2>
                    <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px;">
                        <div class="metric-card">
                            <div class="metric-value">{summary['breakout_momentum_count']}</div>
                            <div class="metric-label">Breakout Momentum</div>
                        </div>
                        <div class="metric-card">
                            <div class="metric-value">{summary['buy_hold_avoid_count']}</div>
                            <div class="metric-label">Buy/Hold/Avoid</div>
                        </div>
                        <div class="metric-card">
                            <div class="metric-value">{summary['stocksight_count']}</div>
                            <div class="metric-label">StockSight Screener</div>
                        </div>
                    </div>
                </div>

                <div class="section">
                    <h2>🏆 Top 10 Performing Stocks</h2>
                    {top_10_html}
                </div>

                <div class="footer">
                    <p><strong>StockSight</strong> - Real-time Stock Analysis Platform</p>
                    <p>This report is generated automatically every morning at 6:00 AM IST</p>
                    <p>For full analysis, visit: <a href="https://myapp-stocksight.streamlit.app/" style="color: #25d366;">StockSight App</a></p>
                    <p style="font-size: 12px; margin-top: 15px; color: #dc3545;">
                        ⚠️ This is not financial advice. Always do your own research.
                    </p>
                </div>
            </div>
        </body>
        </html>
        """

        return html


class EmailService:
    """Handles email sending functionality."""

    def __init__(self):
        self.smtp_server = os.getenv('SMTP_SERVER', 'smtp.gmail.com')
        self.smtp_port = int(os.getenv('SMTP_PORT', '587'))
        self.sender_email = os.getenv('SENDER_EMAIL', '')
        self.sender_password = os.getenv('SENDER_PASSWORD', '')
        self.subscribers = os.getenv('EMAIL_SUBSCRIBERS', '').split(',')

    def send_report(self, html_content: str, subject: str) -> bool:
        """Send HTML report via email."""
        if not all([self.sender_email, self.sender_password, self.subscribers]):
            print("Email configuration incomplete. Please set environment variables.")
            return False

        try:
            # Create message
            msg = MIMEMultipart('alternative')
            msg['Subject'] = subject
            msg['From'] = self.sender_email
            msg['To'] = ', '.join(self.subscribers)

            # Attach HTML content
            html_part = MIMEText(html_content, 'html')
            msg.attach(html_part)

            # Send email
            server = smtplib.SMTP(self.smtp_server, self.smtp_port)
            server.starttls()
            server.login(self.sender_email, self.sender_password)
            server.sendmail(self.sender_email, self.subscribers, msg.as_string())
            server.quit()

            print(f"Report sent successfully to {len(self.subscribers)} subscribers")
            return True

        except Exception as e:
            print(f"Failed to send email: {e}")
            return False


def main():
    """Main function to generate and send daily report."""
    print("Starting StockSight Daily Report Generation...")

    # Generate report
    generator = DailyReportGenerator()
    report_data = generator.generate_consolidated_report()

    if not report_data['success']:
        print(f"Report generation failed: {report_data['message']}")
        return False

    # Generate HTML
    html_report = generator.generate_html_report(report_data)

    # Send email
    email_service = EmailService()
    subject = f"StockSight Daily Report - {generator.report_date}"
    success = email_service.send_report(html_report, subject)

    if success:
        print("Daily report sent successfully!")
        return True
    else:
        print("Failed to send daily report")
        return False


if __name__ == "__main__":
    main()
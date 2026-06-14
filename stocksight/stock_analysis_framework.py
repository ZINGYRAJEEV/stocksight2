"""
Comprehensive Stock Analysis Framework for StockSight.

Implements 7-category stock analysis:
1. Valuation: P/E, P/B, EV/EBITDA, PEG ratios
2. Profitability: Operating margin, ROE, ROCE, Net margin
3. Growth: Revenue CAGR, EPS growth, Order book/guidance
4. Financial Health: Debt-to-Equity, Interest Coverage, Current ratio
5. Cash Flow Quality: OCF vs NP, Free Cash Flow, CFO/PAT ratio
6. Management & Ownership: Promoter holding, pledging, dividend history
7. Relative Strength: 1M/3M/1Y performance vs index, new highs

Each category returns:
- Score (0-100)
- Pass/Fail status
- Key metrics used
"""

import pandas as pd
import numpy as np
from typing import Dict, Tuple, Optional, List, Any
from dataclasses import dataclass, asdict
from enum import Enum
import warnings

warnings.filterwarnings('ignore')


class AnalysisGrade(Enum):
    """Grade for each analysis category."""
    EXCELLENT = "A+"
    VERY_GOOD = "A"
    GOOD = "B+"
    ACCEPTABLE = "B"
    AVERAGE = "C"
    POOR = "D"
    FAIL = "F"


@dataclass
class AnalysisMetrics:
    """Metrics for a stock across all 7 categories."""
    ticker: str
    
    # Valuation scores (0-100)
    valuation_score: float = 0.0
    valuation_grade: str = "F"
    valuation_passed: bool = False
    
    # Profitability scores (0-100)
    profitability_score: float = 0.0
    profitability_grade: str = "F"
    profitability_passed: bool = False
    
    # Growth scores (0-100)
    growth_score: float = 0.0
    growth_grade: str = "F"
    growth_passed: bool = False
    
    # Financial Health scores (0-100)
    fh_score: float = 0.0
    fh_grade: str = "F"
    fh_passed: bool = False
    
    # Cash Flow scores (0-100)
    cf_score: float = 0.0
    cf_grade: str = "F"
    cf_passed: bool = False
    
    # Management & Ownership scores (0-100)
    mgmt_score: float = 0.0
    mgmt_grade: str = "F"
    mgmt_passed: bool = False
    
    # Relative Strength scores (0-100)
    rs_score: float = 0.0
    rs_grade: str = "F"
    rs_passed: bool = False
    
    # Overall scores
    overall_score: float = 0.0  # Average of all 7 categories
    overall_grade: str = "F"
    analysis_passed: bool = False  # True if passes custom thresholds
    
    # Detail dictionaries
    valuation_details: Dict[str, Any] = None
    profitability_details: Dict[str, Any] = None
    growth_details: Dict[str, Any] = None
    fh_details: Dict[str, Any] = None
    cf_details: Dict[str, Any] = None
    mgmt_details: Dict[str, Any] = None
    rs_details: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.valuation_details is None:
            self.valuation_details = {}
        if self.profitability_details is None:
            self.profitability_details = {}
        if self.growth_details is None:
            self.growth_details = {}
        if self.fh_details is None:
            self.fh_details = {}
        if self.cf_details is None:
            self.cf_details = {}
        if self.mgmt_details is None:
            self.mgmt_details = {}
        if self.rs_details is None:
            self.rs_details = {}


class StockAnalysisFramework:
    """Main framework for 7-category stock analysis."""
    
    # Default thresholds (from user specification)
    DEFAULT_THRESHOLDS = {
        "operating_margin_min": 12.0,  # >12%
        "roe_min": 18.0,  # >18%
        "revenue_growth_3y_min": 12.0,  # >12%
        "debt_equity_max": 1.0,  # <1
        "interest_coverage_min": 3.0,  # >3x
        "current_ratio_min": 1.5,  # >1.5
        "cfo_pat_min": 0.8,  # >0.8
        "promoter_holding_min": 50.0,  # >50%
        "pledging_max": 10.0,  # <10%
        "pe_discount_pct": 15.0,  # 15% below sector avg
        "peg_max": 1.0,  # PEG <1 attractive
    }
    
    def __init__(self, thresholds: Optional[Dict[str, float]] = None):
        """
        Initialize framework with optional custom thresholds.
        
        Args:
            thresholds: Override specific thresholds
        """
        self.thresholds = self.DEFAULT_THRESHOLDS.copy()
        if thresholds:
            self.thresholds.update(thresholds)
    
    # ============ VALUATION ANALYSIS ============
    
    def analyze_valuation(self, row: pd.Series) -> Tuple[float, bool, Dict]:
        """
        Analyze valuation metrics.
        
        Checks: P/E vs sector, P/B, EV/EBITDA, PEG ratio
        Score: 0-100
        Pass: True if multiple metrics attractive
        
        Args:
            row: Stock row with valuation data
        
        Returns:
            (score, passed, details_dict)
        """
        details = {}
        scores = []
        
        # P/E Analysis (0-25 points)
        try:
            pe = float(row.get("PE", 0)) or 0
            sector_pe = float(row.get("Sector_PE", pe)) or pe
            
            if pe > 0 and sector_pe > 0:
                pe_discount = ((sector_pe - pe) / sector_pe) * 100
                details["pe"] = pe
                details["sector_pe"] = sector_pe
                details["pe_discount_pct"] = pe_discount
                
                if pe_discount >= self.thresholds["pe_discount_pct"]:
                    scores.append(25)  # Full points
                elif pe_discount >= self.thresholds["pe_discount_pct"] / 2:
                    scores.append(15)
                elif pe > 0:
                    scores.append(5)
            else:
                scores.append(0)
        except (ValueError, TypeError):
            scores.append(0)
        
        # P/B Analysis (0-20 points)
        try:
            pb = float(row.get("PB", 0)) or 0
            if 0 < pb <= 2.0:
                scores.append(20)
            elif pb <= 3.0:
                scores.append(12)
            elif pb > 0:
                scores.append(5)
            else:
                scores.append(0)
            details["pb"] = pb
        except (ValueError, TypeError):
            scores.append(0)
        
        # EV/EBITDA Analysis (0-20 points)
        try:
            ev_ebitda = float(row.get("EV_EBITDA", 0)) or 0
            if 0 < ev_ebitda <= 12:
                scores.append(20)
            elif ev_ebitda <= 15:
                scores.append(12)
            elif ev_ebitda > 0:
                scores.append(5)
            else:
                scores.append(0)
            details["ev_ebitda"] = ev_ebitda
        except (ValueError, TypeError):
            scores.append(0)
        
        # PEG Analysis (0-35 points)
        try:
            peg = float(row.get("PEG", 0)) or 0
            eps_growth = float(row.get("EPS_Growth", 0)) or 0
            
            if peg > 0:
                if peg < self.thresholds["peg_max"]:
                    scores.append(35)  # Attractive
                elif peg < 1.5:
                    scores.append(25)
                elif peg < 2.0:
                    scores.append(15)
                else:
                    scores.append(5)
            else:
                scores.append(0)
            
            details["peg"] = peg
            details["eps_growth"] = eps_growth
        except (ValueError, TypeError):
            scores.append(0)
        
        # Calculate score and pass status
        score = np.mean(scores) if scores else 0
        passed = score >= 60  # Pass if >= 60
        
        return score, passed, details
    
    # ============ PROFITABILITY ANALYSIS ============
    
    def analyze_profitability(self, row: pd.Series) -> Tuple[float, bool, Dict]:
        """
        Analyze profitability metrics.
        
        Checks: Operating margin (>12%), ROE (>18%), ROCE, Net margin trend
        Score: 0-100
        Pass: True if key metrics meet thresholds
        """
        details = {}
        scores = []
        
        # Operating Margin (0-30 points)
        try:
            opm = float(row.get("Operating_Margin", 0)) or 0
            details["operating_margin"] = opm
            
            if opm >= self.thresholds["operating_margin_min"]:
                scores.append(30)
            elif opm >= 8:
                scores.append(20)
            elif opm > 0:
                scores.append(10)
            else:
                scores.append(0)
        except (ValueError, TypeError):
            scores.append(0)
        
        # ROE (0-35 points)
        try:
            roe = float(row.get("ROE", 0)) or 0
            details["roe"] = roe
            
            if roe >= self.thresholds["roe_min"]:
                scores.append(35)
            elif roe >= 15:
                scores.append(25)
            elif roe >= 12:
                scores.append(15)
            elif roe > 0:
                scores.append(8)
            else:
                scores.append(0)
        except (ValueError, TypeError):
            scores.append(0)
        
        # ROCE (0-20 points)
        try:
            roce = float(row.get("ROCE", 0)) or 0
            details["roce"] = roce
            
            if roce >= 18:
                scores.append(20)
            elif roce >= 15:
                scores.append(15)
            elif roce >= 12:
                scores.append(10)
            elif roce > 0:
                scores.append(5)
            else:
                scores.append(0)
        except (ValueError, TypeError):
            scores.append(0)
        
        # Net Margin Trend (0-15 points)
        try:
            nm = float(row.get("Net_Margin", 0)) or 0
            nm_trend = float(row.get("Net_Margin_Trend", 0)) or 0  # YoY change
            details["net_margin"] = nm
            details["net_margin_trend"] = nm_trend
            
            if nm_trend > 0:  # Expanding
                scores.append(15)
            elif nm > 5:
                scores.append(10)
            elif nm > 0:
                scores.append(5)
            else:
                scores.append(0)
        except (ValueError, TypeError):
            scores.append(0)
        
        score = np.mean(scores) if scores else 0
        # Pass if operating margin AND ROE meet minimum thresholds
        passed = (float(row.get("Operating_Margin", 0)) or 0 >= self.thresholds["operating_margin_min"] and
                  float(row.get("ROE", 0)) or 0 >= self.thresholds["roe_min"])
        
        return score, passed, details
    
    # ============ GROWTH ANALYSIS ============
    
    def analyze_growth(self, row: pd.Series) -> Tuple[float, bool, Dict]:
        """
        Analyze growth metrics.
        
        Checks: Revenue CAGR (>12%), EPS growth vs revenue growth, Guidance
        Score: 0-100
        Pass: True if meets growth thresholds
        """
        details = {}
        scores = []
        
        # Revenue CAGR 3Y (0-35 points)
        try:
            rev_cagr = float(row.get("Revenue_CAGR_3Y", 0)) or 0
            details["revenue_cagr_3y"] = rev_cagr
            
            if rev_cagr >= self.thresholds["revenue_growth_3y_min"]:
                scores.append(35)
            elif rev_cagr >= 10:
                scores.append(25)
            elif rev_cagr >= 5:
                scores.append(15)
            elif rev_cagr > 0:
                scores.append(8)
            else:
                scores.append(0)
        except (ValueError, TypeError):
            scores.append(0)
        
        # EPS Growth vs Revenue Growth (0-30 points)
        try:
            eps_growth = float(row.get("EPS_Growth", 0)) or 0
            rev_growth = float(row.get("Revenue_Growth", 0)) or 0
            details["eps_growth"] = eps_growth
            details["revenue_growth"] = rev_growth
            
            if eps_growth > rev_growth and eps_growth >= 15:
                scores.append(30)  # EPS outpacing revenue
            elif eps_growth >= rev_growth and eps_growth >= 12:
                scores.append(22)
            elif eps_growth >= rev_growth:
                scores.append(15)
            elif eps_growth > 0:
                scores.append(8)
            else:
                scores.append(0)
        except (ValueError, TypeError):
            scores.append(0)
        
        # Order Book / Guidance (0-20 points)
        try:
            order_book = float(row.get("Order_Book", 0)) or 0
            guidance_met = int(row.get("Guidance_Met", 0)) or 0  # 1=yes, 0=no
            details["order_book"] = order_book
            details["guidance_met"] = guidance_met
            
            if guidance_met:
                scores.append(15)
            if order_book > 0:
                scores.append(10)
            elif order_book == 0:
                scores.append(5)
        except (ValueError, TypeError):
            scores.append(0)
        
        score = np.mean(scores) if scores else 0
        passed = (float(row.get("Revenue_CAGR_3Y", 0)) or 0 >= self.thresholds["revenue_growth_3y_min"])
        
        return score, passed, details
    
    # ============ FINANCIAL HEALTH ANALYSIS ============
    
    def analyze_financial_health(self, row: pd.Series) -> Tuple[float, bool, Dict]:
        """
        Analyze financial health metrics.
        
        Checks: Debt-to-Equity (<1), Interest Coverage (>3x), Current ratio (>1.5)
        Score: 0-100
        Pass: True if all key metrics pass
        """
        details = {}
        scores = []
        
        # Debt-to-Equity (0-35 points)
        try:
            de = float(row.get("Debt_Equity", 0)) or 0
            details["debt_equity"] = de
            
            if de < 0.5:  # Conservative
                scores.append(35)
            elif de < self.thresholds["debt_equity_max"]:
                scores.append(28)
            elif de < 1.5:
                scores.append(18)
            elif de < 2.0:
                scores.append(10)
            elif de >= 0:
                scores.append(5)
            else:
                scores.append(0)
        except (ValueError, TypeError):
            scores.append(0)
        
        # Interest Coverage Ratio (0-35 points)
        try:
            icr = float(row.get("Interest_Coverage", 0)) or 0
            details["interest_coverage"] = icr
            
            if icr >= self.thresholds["interest_coverage_min"]:
                scores.append(35)
            elif icr >= 2.0:
                scores.append(25)
            elif icr >= 1.5:
                scores.append(15)
            elif icr > 0:
                scores.append(8)
            else:
                scores.append(0)
        except (ValueError, TypeError):
            scores.append(0)
        
        # Current Ratio (0-30 points)
        try:
            cr = float(row.get("Current_Ratio", 0)) or 0
            details["current_ratio"] = cr
            
            if cr >= self.thresholds["current_ratio_min"]:
                scores.append(30)
            elif cr >= 1.2:
                scores.append(20)
            elif cr >= 1.0:
                scores.append(12)
            elif cr > 0:
                scores.append(6)
            else:
                scores.append(0)
        except (ValueError, TypeError):
            scores.append(0)
        
        score = np.mean(scores) if scores else 0
        # Pass if D/E < 1 AND Interest Coverage > 3x AND Current ratio > 1.5
        passed = (float(row.get("Debt_Equity", 0)) or 0 < self.thresholds["debt_equity_max"] and
                  float(row.get("Interest_Coverage", 0)) or 0 >= self.thresholds["interest_coverage_min"] and
                  float(row.get("Current_Ratio", 0)) or 0 >= self.thresholds["current_ratio_min"])
        
        return score, passed, details
    
    # ============ CASH FLOW QUALITY ANALYSIS ============
    
    def analyze_cash_flow(self, row: pd.Series) -> Tuple[float, bool, Dict]:
        """
        Analyze cash flow quality metrics.
        
        Checks: OCF vs NP (close/higher), Free Cash Flow, CFO/PAT ratio (>0.8)
        Score: 0-100
        Pass: True if cash flow quality metrics pass
        """
        details = {}
        scores = []
        
        # OCF vs Net Profit (0-35 points)
        try:
            ocf = float(row.get("Operating_Cash_Flow", 0)) or 0
            np_val = float(row.get("Net_Profit", 0)) or 0
            details["ocf"] = ocf
            details["net_profit"] = np_val
            
            if np_val > 0:
                ocf_to_np = ocf / np_val
                details["ocf_to_np_ratio"] = ocf_to_np
                
                if ocf_to_np >= 1.0:  # OCF >= NP (best case)
                    scores.append(35)
                elif ocf_to_np >= 0.9:
                    scores.append(28)
                elif ocf_to_np >= 0.8:
                    scores.append(20)
                elif ocf_to_np >= 0.7:
                    scores.append(12)
                else:
                    scores.append(5)
            else:
                scores.append(0)
        except (ValueError, TypeError):
            scores.append(0)
        
        # Free Cash Flow (0-35 points)
        try:
            fcf = float(row.get("Free_Cash_Flow", 0)) or 0
            capex = float(row.get("CapEx", 0)) or 0
            details["fcf"] = fcf
            details["capex"] = capex
            
            if fcf > 0:
                scores.append(35)
            elif fcf == 0:
                scores.append(18)
            else:
                # Negative FCF is concerning
                scores.append(5)
        except (ValueError, TypeError):
            scores.append(0)
        
        # CFO/PAT Ratio (0-30 points)
        try:
            cfo_pat = float(row.get("CFO_PAT_Ratio", 0)) or 0
            details["cfo_pat_ratio"] = cfo_pat
            
            if cfo_pat >= self.thresholds["cfo_pat_min"]:
                scores.append(30)
            elif cfo_pat >= 0.7:
                scores.append(22)
            elif cfo_pat >= 0.6:
                scores.append(15)
            elif cfo_pat > 0:
                scores.append(8)
            else:
                scores.append(0)
        except (ValueError, TypeError):
            scores.append(0)
        
        score = np.mean(scores) if scores else 0
        passed = (float(row.get("CFO_PAT_Ratio", 0)) or 0 >= self.thresholds["cfo_pat_min"] and
                  float(row.get("Free_Cash_Flow", 0)) or 0 > 0)
        
        return score, passed, details
    
    # ============ MANAGEMENT & OWNERSHIP ANALYSIS ============
    
    def analyze_management(self, row: pd.Series) -> Tuple[float, bool, Dict]:
        """
        Analyze management quality and ownership metrics.
        
        Checks: Promoter holding (>50%), Pledging (<10%), Dividend/buyback history
        Score: 0-100
        Pass: True if meets ownership criteria
        """
        details = {}
        scores = []
        
        # Promoter Holding (0-40 points)
        try:
            promoter = float(row.get("Promoter_Holding", 0)) or 0
            details["promoter_holding"] = promoter
            
            if promoter >= self.thresholds["promoter_holding_min"]:
                scores.append(40)
            elif promoter >= 40:
                scores.append(30)
            elif promoter >= 30:
                scores.append(20)
            elif promoter > 0:
                scores.append(10)
            else:
                scores.append(0)
        except (ValueError, TypeError):
            scores.append(0)
        
        # Pledging (0-35 points) - lower is better
        try:
            pledging = float(row.get("Pledging", 0)) or 0
            details["pledging"] = pledging
            
            if pledging < self.thresholds["pledging_max"]:
                scores.append(35)
            elif pledging < 20:
                scores.append(25)
            elif pledging < 30:
                scores.append(15)
            elif pledging >= 0:
                scores.append(8)
            else:
                scores.append(0)
        except (ValueError, TypeError):
            scores.append(0)
        
        # Dividend / Buyback History (0-25 points)
        try:
            div_history = int(row.get("Dividend_Years", 0)) or 0  # Years of consistent dividend
            buyback = int(row.get("Buyback_Done", 0)) or 0  # 1=yes, 0=no
            details["dividend_years"] = div_history
            details["buyback_done"] = buyback
            
            if div_history >= 10:
                scores.append(25)
            elif div_history >= 5:
                scores.append(18)
            elif div_history > 0:
                scores.append(12)
            elif buyback:
                scores.append(15)
            else:
                scores.append(5)
        except (ValueError, TypeError):
            scores.append(0)
        
        score = np.mean(scores) if scores else 0
        passed = (float(row.get("Promoter_Holding", 0)) or 0 >= self.thresholds["promoter_holding_min"] and
                  float(row.get("Pledging", 0)) or 0 < self.thresholds["pledging_max"])
        
        return score, passed, details
    
    # ============ RELATIVE STRENGTH ANALYSIS ============
    
    def analyze_relative_strength(self, row: pd.Series) -> Tuple[float, bool, Dict]:
        """
        Analyze relative strength metrics.
        
        Checks: 1M, 3M, 1Y performance vs index, New highs while market flat
        Score: 0-100
        Pass: True if momentum is positive
        """
        details = {}
        scores = []
        
        # 1M Performance vs Index (0-20 points)
        try:
            rs_1m = float(row.get("RS_1M", 0)) or 0
            details["rs_1m_pct"] = rs_1m
            
            if rs_1m > 5:
                scores.append(20)
            elif rs_1m > 2:
                scores.append(15)
            elif rs_1m > 0:
                scores.append(10)
            elif rs_1m >= -2:
                scores.append(5)
            else:
                scores.append(2)
        except (ValueError, TypeError):
            scores.append(0)
        
        # 3M Performance vs Index (0-25 points)
        try:
            rs_3m = float(row.get("RS_3M", 0)) or 0
            details["rs_3m_pct"] = rs_3m
            
            if rs_3m > 10:
                scores.append(25)
            elif rs_3m > 5:
                scores.append(18)
            elif rs_3m > 0:
                scores.append(12)
            elif rs_3m >= -3:
                scores.append(6)
            else:
                scores.append(2)
        except (ValueError, TypeError):
            scores.append(0)
        
        # 1Y Performance vs Index (0-25 points)
        try:
            rs_1y = float(row.get("RS_1Y", 0)) or 0
            details["rs_1y_pct"] = rs_1y
            
            if rs_1y > 30:
                scores.append(25)
            elif rs_1y > 15:
                scores.append(18)
            elif rs_1y > 0:
                scores.append(12)
            elif rs_1y >= -5:
                scores.append(6)
            else:
                scores.append(2)
        except (ValueError, TypeError):
            scores.append(0)
        
        # New Highs while Market Flat (0-30 points) - momentum signal
        try:
            at_new_high = int(row.get("At_New_High", 0)) or 0
            market_direction = str(row.get("Market_Direction", "")).lower()
            details["at_new_high"] = at_new_high
            details["market_direction"] = market_direction
            
            if at_new_high and market_direction in ["flat", "sideways"]:
                scores.append(30)  # Strong momentum signal
            elif at_new_high:
                scores.append(20)
            else:
                scores.append(5)
        except (ValueError, TypeError):
            scores.append(0)
        
        score = np.mean(scores) if scores else 0
        # Pass if positive momentum overall
        passed = (float(row.get("RS_1Y", 0)) or 0 > 0)
        
        return score, passed, details
    
    # ============ OVERALL ANALYSIS ============
    
    def analyze_stock(self, row: pd.Series) -> AnalysisMetrics:
        """
        Perform complete 7-category analysis on a stock.
        
        Args:
            row: Stock data row
        
        Returns:
            AnalysisMetrics with all scores and details
        """
        ticker = str(row.get("Ticker", "UNKNOWN"))
        metrics = AnalysisMetrics(ticker=ticker)
        
        # Run each analysis
        metrics.valuation_score, metrics.valuation_passed, metrics.valuation_details = \
            self.analyze_valuation(row)
        
        metrics.profitability_score, metrics.profitability_passed, metrics.profitability_details = \
            self.analyze_profitability(row)
        
        metrics.growth_score, metrics.growth_passed, metrics.growth_details = \
            self.analyze_growth(row)
        
        metrics.fh_score, metrics.fh_passed, metrics.fh_details = \
            self.analyze_financial_health(row)
        
        metrics.cf_score, metrics.cf_passed, metrics.cf_details = \
            self.analyze_cash_flow(row)
        
        metrics.mgmt_score, metrics.mgmt_passed, metrics.mgmt_details = \
            self.analyze_management(row)
        
        metrics.rs_score, metrics.rs_passed, metrics.rs_details = \
            self.analyze_relative_strength(row)
        
        # Calculate overall score
        all_scores = [
            metrics.valuation_score,
            metrics.profitability_score,
            metrics.growth_score,
            metrics.fh_score,
            metrics.cf_score,
            metrics.mgmt_score,
            metrics.rs_score
        ]
        metrics.overall_score = np.mean(all_scores)
        
        # Assign grades
        metrics.valuation_grade = self._score_to_grade(metrics.valuation_score)
        metrics.profitability_grade = self._score_to_grade(metrics.profitability_score)
        metrics.growth_grade = self._score_to_grade(metrics.growth_score)
        metrics.fh_grade = self._score_to_grade(metrics.fh_score)
        metrics.cf_grade = self._score_to_grade(metrics.cf_score)
        metrics.mgmt_grade = self._score_to_grade(metrics.mgmt_score)
        metrics.rs_grade = self._score_to_grade(metrics.rs_score)
        metrics.overall_grade = self._score_to_grade(metrics.overall_score)
        
        # Overall pass status (custom thresholds)
        # Pass if profitability and growth passed AND good overall score
        metrics.analysis_passed = (
            metrics.profitability_passed and
            metrics.growth_passed and
            metrics.overall_score >= 65
        )
        
        return metrics
    
    @staticmethod
    def _score_to_grade(score: float) -> str:
        """Convert 0-100 score to A+/A/B+/B/C/D/F grade."""
        if score >= 95:
            return "A+"
        elif score >= 90:
            return "A"
        elif score >= 85:
            return "B+"
        elif score >= 75:
            return "B"
        elif score >= 65:
            return "C"
        elif score >= 50:
            return "D"
        else:
            return "F"
    
    def enrich_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Add analysis columns to a dataframe.
        
        Args:
            df: Input dataframe with stock data
        
        Returns:
            Dataframe with analysis columns added
        """
        if df is None or df.empty:
            return df
        
        results = []
        for idx, row in df.iterrows():
            metrics = self.analyze_stock(row)
            results.append(metrics)
        
        analysis_df = pd.DataFrame([asdict(m) for m in results])
        
        # Merge back with original dataframe
        result = pd.concat([df.reset_index(drop=True), analysis_df], axis=1)
        
        return result


# Convenience functions
def create_framework(custom_thresholds: Optional[Dict[str, float]] = None) -> StockAnalysisFramework:
    """Create a stock analysis framework instance."""
    return StockAnalysisFramework(thresholds=custom_thresholds)


def analyze_dataframe(df: pd.DataFrame,
                     custom_thresholds: Optional[Dict[str, float]] = None) -> pd.DataFrame:
    """
    Analyze a dataframe of stocks using the 7-category framework.
    
    Args:
        df: Stock data dataframe
        custom_thresholds: Optional custom thresholds
    
    Returns:
        Enriched dataframe with analysis scores and grades
    """
    framework = StockAnalysisFramework(thresholds=custom_thresholds)
    return framework.enrich_dataframe(df)

import pandas as pd


def is_valid_red_candle(candle):
    """
    Check if a single candle is a valid RED (bearish) candle where:
      1. Close < Open (it is a red candle)
      2. Body is at least 55% of the total range (High - Low)
    """
    open_price = candle["open"]
    close_price = candle["close"]
    high_price = candle["high"]
    low_price = candle["low"]

    # Must be a red candle
    if close_price >= open_price:
        return False

    body = open_price - close_price
    total_range = high_price - low_price

    if total_range <= 0:
        return False

    # Body must be at least 55% of the total candle range
    return (body / total_range) >= 0.55


def is_valid_green_candle(candle):
    """
    Check if a single candle is a valid GREEN (bullish) candle where:
      1. Close > Open (it is a green candle)
      2. Body is at least 55% of the total range (High - Low)
    """
    open_price = candle["open"]
    close_price = candle["close"]
    high_price = candle["high"]
    low_price = candle["low"]

    # Must be a green candle
    if close_price <= open_price:
        return False

    body = close_price - open_price
    total_range = high_price - low_price

    if total_range <= 0:
        return False

    # Body must be at least 55% of the total candle range
    return (body / total_range) >= 0.55



def is_boring_candle(candle, leg_in_body):
    """
    Check if a single candle is a BORING (consolidation) candle:
      1. Candle body < 45% of the leg-in candle's body
    """
    open_price = candle["open"]
    close_price = candle["close"]
    body = abs(close_price - open_price)

    return body < (0.45 * leg_in_body)


def is_same_day(candle_1, candle_2):
    """
    Check if two candles belong to the same calendar day.
    """
    date_1 = pd.to_datetime(candle_1["timestamp"]).date()
    date_2 = pd.to_datetime(candle_2["timestamp"]).date()
    return date_1 == date_2


def compute_gap_and_overlap(boring_top, boring_body, leg_out_open):
    """
    Given the base's top price, the base's body size, and the leg-out
    candle's open, return the gap and overlap adjustment values.
    """
    has_gap = leg_out_open > boring_top
    effective_open = boring_top if has_gap else leg_out_open
    gap_size = max(0, leg_out_open - boring_top)
    overlap_penetration = max(0, boring_top - leg_out_open)
    penetration_pct = (overlap_penetration / boring_body) * 100 if boring_body > 0 else None

    return {
        "has_gap": has_gap,
        "effective_open": effective_open,
        "gap_size": gap_size,
        "penetration_pct": penetration_pct,
    }


def _build_dbr_candidate(mode, start_index, end_index, leg_in_open, leg_in_body,
                         boring_body, boring_pct, boring_is_green,
                         has_gap, gap_size, penetration_pct,
                         leg_out_open, raw_leg_out_body,
                         adjusted_leg_out_body, rally_candle_count,
                         super_rally_wick=None):
    """
    Build a single DBR candidate dictionary with structured rules and metrics.
    """
    has_valid_penetration = (penetration_pct is not None) and (penetration_pct == penetration_pct)
    overlap_text = (
        f"Leg-out Overlap: {penetration_pct:.1f}% penetration into boring body"
        if has_valid_penetration
        else "Leg-out Overlap: Doji base (no body), penetration not measurable"
    )

    rules_applied = [
        "Leg-in: Red candle (Body >= 55% of Range)",
        f"Base: Boring candle body is {boring_pct:.1f}% of leg-in (< 45%)",
        f"Leg-out: {mode} LEG-OUT",
    ]

    if super_rally_wick is not None:
        rules_applied.append(f"Super Rally Strength: Total Body ({adjusted_leg_out_body:.2f}) > Total Wick ({super_rally_wick:.2f})")

    rules_applied.extend([
        f"Leg-out Open: {leg_out_open:.2f} <= Leg-in Open {leg_in_open:.2f}",
        overlap_text,
        f"Leg-out Gap: {'Gap detected (Open anchored to boring top)' if has_gap else 'No gap'}",
        f"Rally vs Base: Body ({adjusted_leg_out_body:.2f}) > Leg-in ({leg_in_body:.2f}) & Boring ({boring_body:.2f})",
    ])

    details = {
        "rules_applied": rules_applied,
        "metrics": {
            "leg_out_mode": mode,
            "leg_in_body": round(float(leg_in_body), 2),
            "boring_body": round(float(boring_body), 2),
            "boring_ratio_pct": round(float(boring_pct), 1),
            "boring_color": "Green" if boring_is_green else "Red",
            "has_gap": bool(has_gap),
            "gap_size": round(float(gap_size), 2),
            "raw_leg_out_body": round(float(raw_leg_out_body), 2),
            "adjusted_leg_out_body": round(float(adjusted_leg_out_body), 2),
            "rally_candle_count": rally_candle_count,
            "penetration_pct": round(float(penetration_pct), 1) if has_valid_penetration else None,
        }
    }

    return {
        "pattern_type": "DBR",
        "leg_out_mode": "SUPER" if "SUPER" in mode else "SINGLE",
        "start_index": start_index,
        "end_index": end_index,
        "details": details,
    }


def _build_rbr_candidate(mode, start_index, end_index, leg_in_body,
                         boring_body, boring_pct, boring_is_green,
                         has_gap, gap_size, penetration_pct,
                         raw_leg_out_body, adjusted_leg_out_body,
                         rally_candle_count, super_rally_wick=None):
    """
    Build a single RBR candidate dictionary with structured rules and metrics.
    """
    has_valid_penetration = (penetration_pct is not None) and (penetration_pct == penetration_pct)
    overlap_text = (
        f"Leg-out Overlap: {penetration_pct:.1f}% penetration into boring body"
        if has_valid_penetration
        else "Leg-out Overlap: Doji base (no body), penetration not measurable"
    )

    rules_applied = [
        "Leg-in: Green candle (Body >= 55% of Range)",
        f"Base: Boring candle body is {boring_pct:.1f}% of leg-in (< 45%)",
        f"Leg-out: {mode} LEG-OUT",
    ]

    if super_rally_wick is not None:
        rules_applied.append(f"Super Rally Strength: Total Body ({adjusted_leg_out_body:.2f}) > Total Wick ({super_rally_wick:.2f})")

    rules_applied.extend([
        overlap_text,
        f"Leg-out Gap: {'Gap detected (Open anchored to boring top)' if has_gap else 'No gap'}",
        f"Rally vs Base: Body ({adjusted_leg_out_body:.2f}) > Leg-in ({leg_in_body:.2f}) & Boring ({boring_body:.2f})",
    ])

    details = {
        "rules_applied": rules_applied,
        "metrics": {
            "leg_out_mode": mode,
            "leg_in_body": round(float(leg_in_body), 2),
            "boring_body": round(float(boring_body), 2),
            "boring_ratio_pct": round(float(boring_pct), 1),
            "boring_color": "Green" if boring_is_green else "Red",
            "has_gap": bool(has_gap),
            "gap_size": round(float(gap_size), 2),
            "raw_leg_out_body": round(float(raw_leg_out_body), 2),
            "adjusted_leg_out_body": round(float(adjusted_leg_out_body), 2),
            "rally_candle_count": rally_candle_count,
            "penetration_pct": round(float(penetration_pct), 1) if has_valid_penetration else None,
        }
    }

    return {
        "pattern_type": "RBR",
        "leg_out_mode": "SUPER" if "SUPER" in mode else "SINGLE",
        "start_index": start_index,
        "end_index": end_index,
        "details": details,
    }


def dbr(dataframe):
    """
    Scan the dataframe and detect complete DBR patterns:
      Candle 1: Leg-in Red Candle (Body >= 55% of Range)
      Candle 2: Boring Candle (Body < 45% of Leg-in Body)
      
      Leg-Out Detection:
        - 1st leg-out candle itself must have Body >= Total Wick.
        - Leg-out Open must be <= Leg-in Open.
        - Gap Detection: If Leg-out Open > Boring Top, gap is detected and
          effective open is anchored to Boring Top.
        
        Option A: Super Leg-Out (3 Continuous Green Candles):
          - Total 3-candle rally body > Total 3-candle wick.
          - Total 3-candle rally body > Leg-in body & Boring body.
          - Zone spans 5 candles (start_index = i, end_index = i + 4).
          
        Option B: Single Leg-Out (1 Strong Green Candle):
          - Physical Body >= 55% of Range.
          - Adjusted Leg-out body > Leg-in body & Boring body.
          - Zone spans 3 candles (start_index = i, end_index = i + 2).

    Parameters
    ----------
    dataframe : pandas.DataFrame
        OHLCV DataFrame with columns: open, high, low, close, volume

    Returns
    -------
    list of dict
        Candidate zones with keys: pattern_type, start_index, end_index, details
    """
    candidates = []
    n_rows = len(dataframe)

    for i in range(n_rows - 2):
        candle_1 = dataframe.iloc[i]
        candle_2 = dataframe.iloc[i + 1]
        candle_3 = dataframe.iloc[i + 2]

        # -------------------------------------------------------------
        # STEP 1: Check Leg-in Red Candle
        # -------------------------------------------------------------
        if not is_valid_red_candle(candle_1):
            continue

        leg_in_open = candle_1["open"]
        leg_in_body = candle_1["open"] - candle_1["close"]

        # -------------------------------------------------------------
        # STEP 2: Check Boring Candle (Base)
        # -------------------------------------------------------------
        # Leg-in and Boring candle must be on the same calendar day
        if not is_same_day(candle_1, candle_2):
            continue

        if not is_boring_candle(candle_2, leg_in_body):
            continue

        boring_open = candle_2["open"]
        boring_close = candle_2["close"]
        boring_body = abs(boring_close - boring_open)
        boring_is_green = boring_close >= boring_open
        boring_top = boring_close if boring_is_green else boring_open
        boring_pct = (boring_body / leg_in_body) * 100 if leg_in_body > 0 else 0

        # -------------------------------------------------------------
        # STEP 3: Physical Checks & Gap Detection for 1st Leg-Out Candle
        # -------------------------------------------------------------
        leg_out_open = candle_3["open"]
        leg_out_close = candle_3["close"]
        leg_out_high = candle_3["high"]
        leg_out_low = candle_3["low"]

        # 1st leg-out candle must be green
        if leg_out_close <= leg_out_open:
            continue

        # 1st leg-out candle itself MUST have Physical Body >= Total Wick
        candle_3_raw_body = leg_out_close - leg_out_open
        candle_3_raw_range = leg_out_high - leg_out_low
        candle_3_raw_wick = candle_3_raw_range - candle_3_raw_body

        if candle_3_raw_body < candle_3_raw_wick:
            continue

        # Opening of leg-out must be <= opening of leg-in
        if leg_out_open > leg_in_open:
            continue

        # Leg-out must not open below the boring candle's low (base must hold)
        if leg_out_open < candle_2["low"]:
            continue

        # Compute gap and overlap values (anchors effective open if gap detected)
        gap_data = compute_gap_and_overlap(boring_top, boring_body, leg_out_open)
        has_gap = gap_data["has_gap"]
        effective_open = gap_data["effective_open"]
        gap_size = gap_data["gap_size"]
        penetration_pct = gap_data["penetration_pct"]

        # -------------------------------------------------------------
        # STEP 4: Option A - Check for SUPER LEG-OUT (3 Continuous Green Candles)
        # -------------------------------------------------------------
        is_super_leg_out = False

        if i + 4 < n_rows:
            candle_4 = dataframe.iloc[i + 3]
            candle_5 = dataframe.iloc[i + 4]

            # -----------------------------------------------------------------
            # Check follow-through candles (Candle 4 and Candle 5)
            # Rules:
            #   1. Neither candle can be RED (Close < Open).
            #   2. Both candles must be non-red (Close >= Open).
            #   3. At least one of Candle 4 or Candle 5 must be strictly GREEN (Close > Open).
            #   4. If BOTH Candle 4 and Candle 5 are flat (Close == Open), fallback to SINGLE leg-out.
            # -----------------------------------------------------------------
            is_candle_4_green = candle_4["close"] > candle_4["open"]
            is_candle_4_flat = candle_4["close"] == candle_4["open"]
            is_candle_4_valid = is_candle_4_green or is_candle_4_flat

            is_candle_5_green = candle_5["close"] > candle_5["open"]
            is_candle_5_flat = candle_5["close"] == candle_5["open"]
            is_candle_5_valid = is_candle_5_green or is_candle_5_flat

            has_at_least_one_green = is_candle_4_green or is_candle_5_green

            # Both must be valid (non-red), and at least one must be strictly green
            if is_candle_4_valid and is_candle_5_valid and has_at_least_one_green:
                final_super_close = candle_5["close"]
                super_rally_body = final_super_close - effective_open

                # Calculate total range and total wick across the 3-candle rally
                super_rally_high = max(candle_3["high"], candle_4["high"], candle_5["high"])
                super_rally_low = min(candle_3["low"], candle_4["low"], candle_5["low"], effective_open)
                super_rally_range = super_rally_high - super_rally_low
                super_rally_wick = super_rally_range - super_rally_body

                # Check: Super Leg-Out Body MUST be strictly > Total Wick & > Leg-in & Boring bodies
                if super_rally_body > super_rally_wick and super_rally_body > leg_in_body and super_rally_body > boring_body:
                    # A three-candle continuation must not replace the valid
                    # first leg-out zone. The model receives only the original
                    # one-leg-out candidate, never a two-leg-out candidate.
                    is_super_leg_out = False

                    candidate_dict = _build_dbr_candidate(
                        mode="SUPER (3 Candles)",
                        start_index=i,
                        end_index=i + 4,
                        leg_in_open=leg_in_open,
                        leg_in_body=leg_in_body,
                        boring_body=boring_body,
                        boring_pct=boring_pct,
                        boring_is_green=boring_is_green,
                        has_gap=has_gap,
                        gap_size=gap_size,
                        penetration_pct=penetration_pct,
                        leg_out_open=leg_out_open,
                        raw_leg_out_body=candle_3_raw_body,
                        adjusted_leg_out_body=super_rally_body,
                        rally_candle_count=3,
                        super_rally_wick=super_rally_wick,
                    )

        # -------------------------------------------------------------
        # STEP 5: Option B - Check for SINGLE LEG-OUT (1 Strong Green Candle)
        # -------------------------------------------------------------
        if not is_super_leg_out:
            # Single candle must meet the strict Body >= 55% of Range requirement
            if candle_3_raw_range > 0 and (candle_3_raw_body / candle_3_raw_range) >= 0.55:
                single_adjusted_body = candle_3["close"] - effective_open

                if single_adjusted_body > leg_in_body and single_adjusted_body > boring_body:
                    candidate_dict = _build_dbr_candidate(
                        mode="SINGLE (1 Candle)",
                        start_index=i,
                        end_index=i + 2,
                        leg_in_open=leg_in_open,
                        leg_in_body=leg_in_body,
                        boring_body=boring_body,
                        boring_pct=boring_pct,
                        boring_is_green=boring_is_green,
                        has_gap=has_gap,
                        gap_size=gap_size,
                        penetration_pct=penetration_pct,
                        leg_out_open=leg_out_open,
                        raw_leg_out_body=candle_3_raw_body,
                        adjusted_leg_out_body=single_adjusted_body,
                        rally_candle_count=1,
                    )
                    candidates.append(candidate_dict)

    return candidates


def rbr(dataframe):
    """
    Scan the dataframe and detect complete RBR patterns:
      Candle 1: Leg-in Green Candle (Body >= 55% of Range)
      Candle 2: Boring Candle (Body < 45% of Leg-in Body)
      
      Leg-Out Detection:
        - 1st leg-out candle itself must have Body >= Total Wick.
        - Gap Detection: If Leg-out Open > Boring Top, gap is detected and
          effective open is anchored to Boring Top.
        
        Option A: Super Leg-Out (3 Continuous Green Candles):
          - Total 3-candle rally body > Total 3-candle wick.
          - Total 3-candle rally body > Leg-in body & Boring body.
          - Zone spans 5 candles (start_index = i, end_index = i + 4).
          
        Option B: Single Leg-Out (1 Strong Green Candle):
          - Physical Body >= 55% of Range.
          - Adjusted Leg-out body > Leg-in body & Boring body.
          - Zone spans 3 candles (start_index = i, end_index = i + 2).

    Parameters
    ----------
    dataframe : pandas.DataFrame
        OHLCV DataFrame with columns: open, high, low, close, volume

    Returns
    -------
    list of dict
        Candidate zones with keys: pattern_type, start_index, end_index, details
    """
    candidates = []
    n_rows = len(dataframe)

    for i in range(n_rows - 2):
        candle_1 = dataframe.iloc[i]
        candle_2 = dataframe.iloc[i + 1]
        candle_3 = dataframe.iloc[i + 2]

        # -------------------------------------------------------------
        # STEP 1: Check Leg-in Green Candle
        # -------------------------------------------------------------
        if not is_valid_green_candle(candle_1):
            continue

        leg_in_body = candle_1["close"] - candle_1["open"]

        # -------------------------------------------------------------
        # STEP 2: Check Boring Candle (Base)
        # -------------------------------------------------------------
        # Leg-in and Boring candle must be on the same calendar day
        if not is_same_day(candle_1, candle_2):
            continue

        if not is_boring_candle(candle_2, leg_in_body):
            continue

        boring_open = candle_2["open"]
        boring_close = candle_2["close"]
        boring_body = abs(boring_close - boring_open)
        boring_is_green = boring_close >= boring_open
        boring_top = boring_close if boring_is_green else boring_open
        boring_pct = (boring_body / leg_in_body) * 100 if leg_in_body > 0 else 0

        # -------------------------------------------------------------
        # STEP 3: Physical Checks & Gap Detection for 1st Leg-Out Candle
        # -------------------------------------------------------------
        leg_out_open = candle_3["open"]
        leg_out_close = candle_3["close"]
        leg_out_high = candle_3["high"]
        leg_out_low = candle_3["low"]

        # 1st leg-out candle must be green
        if leg_out_close <= leg_out_open:
            continue

        # 1st leg-out candle itself MUST have Physical Body >= Total Wick
        candle_3_raw_body = leg_out_close - leg_out_open
        candle_3_raw_range = leg_out_high - leg_out_low
        candle_3_raw_wick = candle_3_raw_range - candle_3_raw_body

        if candle_3_raw_body < candle_3_raw_wick:
            continue

        # Leg-out must not open below the boring candle's low (base must hold)
        if leg_out_open < candle_2["low"]:
            continue

        # Compute gap and overlap values (anchors effective open if gap detected)
        gap_data = compute_gap_and_overlap(boring_top, boring_body, leg_out_open)
        has_gap = gap_data["has_gap"]
        effective_open = gap_data["effective_open"]
        gap_size = gap_data["gap_size"]
        penetration_pct = gap_data["penetration_pct"]

        # -------------------------------------------------------------
        # STEP 4: Option A - Check for SUPER LEG-OUT (3 Continuous Green Candles)
        # -------------------------------------------------------------
        is_super_leg_out = False

        if i + 4 < n_rows:
            candle_4 = dataframe.iloc[i + 3]
            candle_5 = dataframe.iloc[i + 4]

            # -----------------------------------------------------------------
            # Check follow-through candles (Candle 4 and Candle 5)
            # Rules:
            #   1. Neither candle can be RED (Close < Open).
            #   2. Both candles must be non-red (Close >= Open).
            #   3. At least one of Candle 4 or Candle 5 must be strictly GREEN (Close > Open).
            #   4. If BOTH Candle 4 and Candle 5 are flat (Close == Open), fallback to SINGLE leg-out.
            # -----------------------------------------------------------------
            is_candle_4_green = candle_4["close"] > candle_4["open"]
            is_candle_4_flat = candle_4["close"] == candle_4["open"]
            is_candle_4_valid = is_candle_4_green or is_candle_4_flat

            is_candle_5_green = candle_5["close"] > candle_5["open"]
            is_candle_5_flat = candle_5["close"] == candle_5["open"]
            is_candle_5_valid = is_candle_5_green or is_candle_5_flat

            has_at_least_one_green = is_candle_4_green or is_candle_5_green

            # Both must be valid (non-red), and at least one must be strictly green
            if is_candle_4_valid and is_candle_5_valid and has_at_least_one_green:
                final_super_close = candle_5["close"]
                super_rally_body = final_super_close - effective_open

                # Calculate total range and total wick across the 3-candle rally
                super_rally_high = max(candle_3["high"], candle_4["high"], candle_5["high"])
                super_rally_low = min(candle_3["low"], candle_4["low"], candle_5["low"], effective_open)
                super_rally_range = super_rally_high - super_rally_low
                super_rally_wick = super_rally_range - super_rally_body

                # Check: Super Leg-Out Body MUST be strictly > Total Wick & > Leg-in & Boring bodies
                if super_rally_body > super_rally_wick and super_rally_body > leg_in_body and super_rally_body > boring_body:
                    # A three-candle continuation must not replace the valid
                    # first leg-out zone. The model receives only the original
                    # one-leg-out candidate, never a two-leg-out candidate.
                    is_super_leg_out = False

                    candidate_dict = _build_rbr_candidate(
                        mode="SUPER (3 Candles)",
                        start_index=i,
                        end_index=i + 4,
                        leg_in_body=leg_in_body,
                        boring_body=boring_body,
                        boring_pct=boring_pct,
                        boring_is_green=boring_is_green,
                        has_gap=has_gap,
                        gap_size=gap_size,
                        penetration_pct=penetration_pct,
                        raw_leg_out_body=candle_3_raw_body,
                        adjusted_leg_out_body=super_rally_body,
                        rally_candle_count=3,
                        super_rally_wick=super_rally_wick,
                    )

        # -------------------------------------------------------------
        # STEP 5: Option B - Check for SINGLE LEG-OUT (1 Strong Green Candle)
        # -------------------------------------------------------------
        if not is_super_leg_out:
            # Single candle must meet the strict Body >= 55% of Range requirement
            if candle_3_raw_range > 0 and (candle_3_raw_body / candle_3_raw_range) >= 0.55:
                single_adjusted_body = candle_3["close"] - effective_open

                if single_adjusted_body > leg_in_body and single_adjusted_body > boring_body:
                    candidate_dict = _build_rbr_candidate(
                        mode="SINGLE (1 Candle)",
                        start_index=i,
                        end_index=i + 2,
                        leg_in_body=leg_in_body,
                        boring_body=boring_body,
                        boring_pct=boring_pct,
                        boring_is_green=boring_is_green,
                        has_gap=has_gap,
                        gap_size=gap_size,
                        penetration_pct=penetration_pct,
                        raw_leg_out_body=candle_3_raw_body,
                        adjusted_leg_out_body=single_adjusted_body,
                        rally_candle_count=1,
                    )
                    candidates.append(candidate_dict)

    return candidates


def detect_patterns(dataframe):
    """
    Main entry point called by detector.py and the web app.
    Combines both DBR and RBR candidate patterns.
    """
    dbr_candidates = dbr(dataframe)
    rbr_candidates = rbr(dataframe)

    all_candidates = dbr_candidates + rbr_candidates
    all_candidates.sort(key=lambda item: item["start_index"])

    return all_candidates

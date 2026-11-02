from datetime import timedelta
from dataclasses import replace
import numpy as np
import pandas as pd
import pytest

from spear_shield.indicators.macro import historical_percentile, ratio, style_zscore
from spear_shield.strategy import Evidence, Policy
from spear_shield.strategy.macro import resonance, thermometer


def test_zscore_known_uniform_sequence_and_prefix():
    # 比值1..157，前156均值78.5，方差(156²-1)/12。
    growth = pd.Series(np.arange(1., 158.))
    dividend = pd.Series(np.ones(157))
    z = style_zscore(growth, dividend, ddof=0, include_current=False)
    assert z.iloc[:156].isna().all()
    assert z.iloc[156] == pytest.approx((157-78.5) / np.sqrt((156**2-1)/12))
    included = style_zscore(growth, dividend, ddof=1, include_current=True)
    assert included.iloc[155] == pytest.approx((156-78.5) / growth.iloc[:156].std(ddof=1))
    assert included.iloc[:156].equals(style_zscore(growth.iloc[:156], dividend.iloc[:156],
                                                 ddof=1, include_current=True))


def test_zscore_missing_zero_std_and_length():
    s = pd.Series(np.ones(160))
    assert style_zscore(s, s, ddof=0, include_current=True).isna().all()
    s.iloc[10] = np.nan
    z = style_zscore(s, pd.Series(np.ones(160)), ddof=0, include_current=True)
    assert z.isna().all()


def test_zscore_rejects_daily_or_compressed_weekly_calendar():
    for dates in (pd.date_range("2020-01-01",periods=160,freq="D"),
                  pd.date_range("2020-01-03",periods=161,freq="W-FRI").delete(40)):
        values=pd.Series(np.arange(160.)+1,index=dates)
        with pytest.raises(ValueError):
            style_zscore(values,values,ddof=0,include_current=True)


def test_ratio_units_and_no_fill():
    a, b = pd.Series([2., 3., np.nan, 1.]), pd.Series([100., 0., 10., -1.])
    r = ratio(a, b, percent=True)
    assert r.iloc[0] == 2
    assert r.iloc[1:].isna().all()
    with pytest.raises(ValueError):
        ratio(a, b.rename(index={0: 7}))


@pytest.mark.parametrize("current,expected", [(True, [np.nan,np.nan,100.,100.]),
                                            (False,[np.nan,np.nan,np.nan,100.])])
def test_percentile_ties_and_explicit_window(current, expected):
    actual = historical_percentile(pd.Series([1.,1.,1.,2.]), window=3, include_current=current)
    np.testing.assert_allclose(actual, expected, equal_nan=True)


@pytest.mark.parametrize("a,b,state", [(True,True,"绝对主升浪"), (True,False,"牛市中期回调"),
                                      (False,True,"熊市反弹中继"),(False,False,"绝对主跌浪")])
def test_matrix(a,b,state):
    assert resonance(a,b)["status"] == state
    assert resonance(None,b)["quadrant"] is None


def test_default_five_dimensions_cannot_be_complete(snapshot):
    value = thermometer(snapshot(month_slope=0, zscore=-3), Policy())
    assert value["complete"] is False
    assert value["dimensions"][0].status == "战略防守"
    assert value["dimensions"][1].status == "待确认"
    assert value["dimensions"][3].status == "数据缺失"


def test_future_expired_and_nan_evidence(snapshot):
    s = snapshot(month_slope=1, x=2)
    item = s.facts["x"]
    future = replace(item, available_at=s.as_of+timedelta(hours=1))
    old = Evidence(2,"test",s.as_of-timedelta(days=3),s.as_of-timedelta(days=2),
                   s.as_of-timedelta(days=1))
    for ev in (future,old,replace(item,value=float('inf'))):
        assert replace(s,facts={"x":ev}).get("x") is None
    with pytest.raises(ValueError):
        replace(s,as_of=s.as_of.replace(tzinfo=None))

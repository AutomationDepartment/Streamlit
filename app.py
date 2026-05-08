import streamlit as st
import requests
import pandas as pd
import numpy as np
import os
import plotly.express as px
import calendar

# --- 1. НАСТРОЙКА СТРАНИЦЫ И ПАМЯТИ ---
st.set_page_config(page_title="MPStats Аналитика PRO", layout="wide")

st.markdown(
    """
    <style>
    [data-testid="stMetricValue"] { font-size: 24px !important; }
    [data-testid="stForm"] { border: none; padding: 0; }
    </style>
    """,
    unsafe_allow_html=True
)

if 'history' not in st.session_state:
    st.session_state.history = []
if 'last_search' not in st.session_state:
    st.session_state.last_search = None
if 'authenticated' not in st.session_state:
    st.session_state.authenticated = False

try:
    MPSTATS_TOKEN = st.secrets.get("MPSTATS_TOKEN", os.getenv("MPSTATS_TOKEN"))
except Exception:
    MPSTATS_TOKEN = os.getenv("MPSTATS_TOKEN")

if not MPSTATS_TOKEN:
    st.error("❌ Токен MPStats не найден.")
    st.stop()

if not st.session_state.authenticated:
    MY_PASSWORD = os.getenv("APP_PASSWORD", "123")
    user_password = st.text_input("🔑 Введите пароль для доступа:", type="password")

    if user_password == MY_PASSWORD:
        st.session_state.authenticated = True
        st.rerun()
    elif user_password:
        st.warning("Неверный пароль. Доступ закрыт.")
    st.stop()

# --- СЛОВАРИ ЭНДПОИНТОВ МАРКЕТПЛЕЙСОВ ---
MP_CONFIG = {
    "WB": {
        "trends": {"url": "https://mpstats.io/api/analytics/v1/wb/category/trends", "method": "POST"},
        "sellers": {"url": "https://mpstats.io/api/analytics/v1/wb/category/sellers", "method": "POST"},
        "segmentation": {"url": "https://mpstats.io/api/analytics/v1/wb/category/price_segmentation", "method": "POST"}
    },
    "OZ": {
        "trends": {"url": "https://mpstats.io/api/analytics/v1/oz/category/trends", "method": "POST"},
        "sellers": {"url": "https://mpstats.io/api/analytics/v1/oz/category/sellers", "method": "POST"},
        "segmentation": {"url": "https://mpstats.io/api/analytics/v1/oz/category/price_segmentation", "method": "POST"}
    },
    "YM": {
        "trends": {"url": "https://mpstats.io/api/ym/get/category/trends", "method": "GET"},
        "sellers": {"url": "https://mpstats.io/api/ym/get/category/sellers", "method": "GET"},
        "segmentation": {"url": "https://mpstats.io/api/ym/get/category/price_segmentation", "method": "GET"}
    }
}


# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---
def get_best_month(category_path, token, mp):
    if mp != "WB":
        return "Нет данных"

    URL = "https://mpstats.io/api/analytics/v1/wb/category/season_effects/annual"
    headers = {"X-Mpstats-TOKEN": token, "Content-Type": "application/json"}
    params = {"path": category_path, "period": "month"}

    try:
        res = requests.get(URL, params=params, headers=headers, timeout=30)
        data = res.json()
        items = data.get("data", data) if isinstance(data, dict) else data

        if not items or len(items) == 0: return "Нет данных"

        df = pd.DataFrame(items)
        if 'yearly_revenue' in df.columns:
            df['yearly_revenue'] = pd.to_numeric(df['yearly_revenue'], errors='coerce').fillna(0)
            best_row = df.loc[df['yearly_revenue'].idxmax()]

            months_ru = {
                1: "❄️ Январь", 2: "❄️ Февраль", 3: "🌷 Март", 4: "🌷 Апрель",
                5: "🌷 Май", 6: "☀️ Июнь", 7: "☀️ Июль", 8: "☀️ Август",
                9: "🍂 Сентябрь", 10: "🍂 Октябрь", 11: "🍂 Ноябрь", 12: "❄️ Декабрь"
            }

            month_val = best_row.get('date', best_row.get('month', best_row.get('name')))

            if pd.notnull(month_val):
                try:
                    return months_ru.get(int(month_val), str(month_val))
                except:
                    if isinstance(month_val, str) and "-" in month_val:
                        parts = month_val.split("-")
                        try:
                            m = int(parts[1]) if len(parts[0]) == 4 else int(parts[0])
                            return months_ru.get(m, month_val)
                        except:
                            pass
                    return str(month_val).capitalize()
        return "Неизвестно"
    except Exception:
        return "Ошибка API"


def normalize_score(series):
    s_min, s_max = series.min(), series.max()
    if s_min == s_max: return pd.Series([0] * len(series), index=series.index)
    return (series - s_min) / (s_max - s_min)


def get_best_price_pocket(category_path, target_date, token, mp):
    ep = MP_CONFIG[mp].get("segmentation")
    if not ep: return "Нет данных", "Нет данных", "Нет данных"

    headers = {"X-Mpstats-TOKEN": token, "Content-Type": "application/json"}
    year, month = target_date.year, target_date.month
    last_day = calendar.monthrange(year, month)[1]

    d1 = f"{year}-{month:02d}-01"
    d2 = f"{year}-{month:02d}-{last_day}"

    params = {
        "path": category_path,
        "d1": d1, "d2": d2,
        "fbs": 0, "minPrice": 500, "maxPrice": 4000
    }

    try:
        res = requests.request(ep["method"], ep["url"], params=params, headers=headers, timeout=30)
        if res.status_code != 200: return "Ошибка API", "Ошибка API", "Ошибка API"

        raw = res.json()
        data_seg = raw.get("data", raw) if isinstance(raw, dict) else raw
        if not data_seg or len(data_seg) == 0: return "Нет данных", "Нет данных", "Нет данных"

        df_seg = pd.DataFrame(data_seg)

        def get_col_val(r, col_est, col_base):
            v = float(r.get(col_est, 0) or 0)
            return v if v > 0 else float(r.get(col_base, 0) or 0)

        df_seg['calc_rev'] = df_seg.apply(lambda r: get_col_val(r, 'revenue_estimated', 'revenue'), axis=1)
        df_seg['calc_sal'] = df_seg.apply(lambda r: get_col_val(r, 'sales_estimated', 'sales'), axis=1)

        for c in ['lost_profit', 'revenue', 'items_with_sells', 'items']:
            if c in df_seg.columns:
                df_seg[c] = pd.to_numeric(df_seg[c], errors='coerce').fillna(0)

        df_seg['lost_revenue'] = (df_seg.get('lost_profit', 0) / df_seg.get('revenue', 1)).replace([np.inf, -np.inf],
                                                                                                   0).fillna(0)
        df_seg['efficiency_items'] = (df_seg['calc_rev'] / df_seg.get('items_with_sells', 1)).replace([np.inf, -np.inf],
                                                                                                      0).fillna(0)
        df_seg['average_check'] = (df_seg['calc_rev'] / df_seg['calc_sal']).replace([np.inf, -np.inf], 0).fillna(0)

        sum_rev = df_seg['calc_rev'].sum()
        df_seg['pocket_weight'] = (df_seg['calc_rev'] / sum_rev).replace([np.inf, -np.inf], 0).fillna(
            0) if sum_rev > 0 else 0

        eff_norm = normalize_score(df_seg['efficiency_items'])
        lost_norm = normalize_score(df_seg['lost_revenue'])
        aver_norm = normalize_score(df_seg['average_check'])
        weight_norm = normalize_score(df_seg['pocket_weight'])

        df_seg['price_score'] = (eff_norm * 0.30 + lost_norm * 0.15 + aver_norm * 0.15 + weight_norm * 0.40).round(2)
        df_seg = df_seg.sort_values(by='price_score', ascending=False)

        pocket_col = 'range' if 'range' in df_seg.columns else 'name'
        top_pockets = [f"{name} ₽" for name in df_seg[pocket_col].head(3).tolist()]

        while len(top_pockets) < 3: top_pockets.append("Нет данных")
        return top_pockets[0], top_pockets[1], top_pockets[2]
    except Exception:
        return "Ошибка расчета", "Ошибка расчета", "Ошибка расчета"


# --- ИЗМЕНЕННАЯ ФУНКЦИЯ ДЛЯ АНАЛИЗА МОНОПОЛИИ (Учет 2х лидеров) ---
def get_monopoly_status(category_path, target_date, token, mp):
    ep = MP_CONFIG[mp]["sellers"]
    headers = {"X-Mpstats-TOKEN": token, "Content-Type": "application/json"}
    year, month = target_date.year, target_date.month
    last_day = calendar.monthrange(year, month)[1]

    params = {
        "path": category_path,
        "d1": f"{year}-{month:02d}-01",
        "d2": f"{year}-{month:02d}-{last_day}"
    }

    try:
        res = requests.request(ep["method"], ep["url"], params=params, headers=headers, timeout=30)
        data = res.json()
        sellers = data.get("data", data) if isinstance(data, dict) else data

        if not sellers or len(sellers) == 0: return "Нет данных", "Нет данных", 0, 0, 0

        sdf = pd.DataFrame(sellers)

        def get_seller_rev(r):
            est = float(r.get('revenue_estimated', 0) or 0)
            return est if est > 0 else float(r.get('revenue', 0) or 0)

        sdf['rev'] = sdf.apply(get_seller_rev, axis=1)
        total_rev = sdf['rev'].sum()
        if total_rev == 0: return "Нулевая выручка", "Нет", 0, 0, 0

        sdf = sdf.sort_values('rev', ascending=False)
        sdf['share'] = (sdf['rev'] / total_rev) * 100

        cr1 = sdf['share'].iloc[0] if len(sdf) > 0 else 0
        cr5 = sdf['share'].head(5).sum() if len(sdf) >= 5 else 100
        hhi = (sdf['share'] ** 2).sum()

        # Достаем доли 2 и 3 места
        share_2 = sdf['share'].iloc[1] if len(sdf) > 1 else 0
        share_3 = sdf['share'].iloc[2] if len(sdf) > 2 else 0

        # Новая логика (Дуополия)
        if cr1 > 30:
            leader_status = "Монополист"
        elif share_2 > 0 and (cr1 / share_2) >= 2:
            leader_status = "Есть (Один)"
        elif share_3 > 0 and (share_2 / share_3) >= 2:
            leader_status = "Два лидера"
        elif len(sdf) == 2 and share_2 > 0:  # Защита, если в нише всего 2 продавца
            leader_status = "Два лидера"
        else:
            leader_status = "Нет"

        if cr1 > 30:
            status = "🚨 Монополия"
        elif hhi > 600 or cr5 > 40:
            status = "⚠️ Высокая"
        elif hhi >= 500:
            status = "📊 Умеренная"
        else:
            status = "✅ Слабая"

        return status, leader_status, round(hhi, 0), round(cr1, 1), round(cr5, 1)
    except:
        return "Ошибка расчета", "Ошибка", 0, 0, 0


# --- 2. БЛОК ПОИСКА И ОСНОВНОЙ СКРИПТ ---
st.title("📊 Аналитика и сравнение категорий MPStats")
st.info("⚠️ **Обратите внимание:** при поиске и анализе одной категории тратятся **2 лимита** запросов к API MPStats.")

with st.form(key="search_form"):
    col_mp, col_input, col_btn = st.columns([1, 4, 1])
    with col_mp:
        MP = st.selectbox("Маркетплейс:", ["WB", "OZ", "YM"], label_visibility="collapsed")
    with col_input:
        CATEGORY = st.text_input("📁 Введите путь категории:", label_visibility="collapsed",
                                 placeholder="Дом/Уборка/Швабры")
    with col_btn:
        search_clicked = st.form_submit_button("🚀 Найти и добавить", type="primary", use_container_width=True)

if search_clicked:
    if not CATEGORY:
        st.warning("⚠️ Пожалуйста, введите категорию.")
    else:
        with st.spinner(f'Загрузка данных ({MP})...'):
            ep_trends = MP_CONFIG[MP]["trends"]
            headers = {"X-Mpstats-TOKEN": MPSTATS_TOKEN, "Content-Type": "application/json"}
            params_t = {"path": CATEGORY, "view": "itemsInCategory", "trends_by": "month"}

            try:
                res_trends = requests.request(ep_trends["method"], ep_trends["url"], params=params_t, headers=headers,
                                              timeout=30)
                if res_trends.status_code != 200:
                    st.error(f"Ошибка API: {res_trends.status_code}")
                    st.stop()

                raw_data = res_trends.json()
                data_list = raw_data.get("data", raw_data) if isinstance(raw_data, dict) else raw_data
                df = pd.DataFrame(data_list)

                if df.empty:
                    st.error("Данные по категории не найдены.")
                    st.stop()
            except Exception as e:
                st.error(f"Ошибка связи: {e}")
                st.stop()

            df['date_dt'] = pd.to_datetime(df['date'], format='%Y-%m-%d', errors='coerce')
            df = df.sort_values(by='date_dt', ascending=False)


            def get_row_rev(row):
                return float(row.get('revenue_estimated', row.get('revenue', 0)) or 0)


            df['rev_fallback'] = df.apply(get_row_rev, axis=1)
            valid_months = df[df['rev_fallback'] > 0]

            if valid_months.empty:
                st.error("Не найдено закрытых месяцев с выручкой > 0")
                st.stop()

            latest_date = valid_months['date_dt'].iloc[0]
            prev_year_date = latest_date - pd.DateOffset(years=1)
            row_latest = df[df['date_dt'] == latest_date]
            row_prev = df[df['date_dt'] == prev_year_date]

            # --- ЗАПРОСЫ ДОП. ДАННЫХ ---
            m_status, m_leader, m_hhi, m_cr1, m_cr5 = get_monopoly_status(CATEGORY, latest_date, MPSTATS_TOKEN, MP)
            m_best_month = get_best_month(CATEGORY, MPSTATS_TOKEN, MP)
            p1, p2, p3 = get_best_price_pocket(CATEGORY, latest_date, MPSTATS_TOKEN, MP)


            def get_val(row, col):
                try:
                    v = row[col].iloc[0]
                    return float(v) if pd.notnull(v) and str(v).strip() != '' else 0
                except:
                    return 0


            def get_fb(row, c1, c2):
                v = get_val(row, c1)
                return v if v != 0 else get_val(row, c2)


            def growth(c, p):
                return round(((c - p) / p * 100), 1) if p != 0 else 0


            rev_l = get_fb(row_latest, 'revenue_estimated', 'revenue')
            rev_p = get_fb(row_prev, 'revenue_estimated', 'revenue')
            sal_l = get_fb(row_latest, 'sales_estimated', 'sales')
            sal_p = get_fb(row_prev, 'sales_estimated', 'sales')
            items_l = get_val(row_latest, 'items_with_sells')
            items_p = get_val(row_prev, 'items_with_sells')
            aov_l = rev_l / sal_l if sal_l > 0 else 0
            aov_p = rev_p / sal_p if sal_p > 0 else 0
            rev_item_l = rev_l / items_l if items_l > 0 else 0
            rev_item_p = rev_p / items_p if items_p > 0 else 0

            new_record = {
                "МП": MP,
                "Категория": CATEGORY,
                "Лучший месяц": m_best_month,
                "Карман №1": p1,
                "Карман №2": p2,
                "Карман №3": p3,
                "Конкуренция на рынке": m_status,
                "Наличие лидера": m_leader,
                "Индекс HHI": int(m_hhi),
                "Доля лидера, %": m_cr1,
                "Доля ТОП-5, %": m_cr5,
                "Выручка, ₽": int(rev_l),
                "Рост выручки, %": growth(rev_l, rev_p),
                "Товары с прод.": int(items_l),
                "Рост тов. с прод, %": growth(items_l, items_p),
                "Продажи, шт": int(sal_l),
                "Рост продаж, %": growth(sal_l, sal_p),
                "Сред. выручка/товар, ₽": int(rev_item_l),
                "Рост выр/товар, %": growth(rev_item_l, rev_item_p),
                "Средний чек, ₽": int(aov_l),
                "Рост чека, %": growth(aov_l, aov_p)
            }

            st.session_state.last_search = {
                "mp": MP,
                "name": CATEGORY.split("/")[-1],
                "rec": new_record,
                "dates": f"{latest_date.strftime('%m.%Y')} vs {prev_year_date.strftime('%m.%Y')}",
                "monopoly": {"status": m_status, "leader": m_leader, "hhi": m_hhi, "cr1": m_cr1, "cr5": m_cr5},
                "season": m_best_month,
                "pockets": [p1, p2, p3]
            }

            idx = next(
                (i for (i, d) in enumerate(st.session_state.history) if d["МП"] == MP and d["Категория"] == CATEGORY),
                None)
            if idx is not None:
                st.session_state.history[idx] = new_record
            else:
                st.session_state.history.append(new_record)

# --- 3. ВЕРХНЯЯ КАРТОЧКА ---
if st.session_state.last_search:
    ls = st.session_state.last_search
    r, mon = ls["rec"], ls["monopoly"]
    season, pockets = ls.get("season", "Нет данных"), ls.get("pockets", ["Нет данных", "Нет данных", "Нет данных"])


    def fmt(v): return f"{int(v):,}".replace(",", " ")


    st.success(f"✅ Аналитика ({ls['mp']}) по категории **{ls['name']}** обновлена!")
    st.subheader(f"Детально: {ls['name']} ({ls['dates']})")

    st.markdown("##### 💰 Финансовые показатели")
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Выручка", f"{fmt(r['Выручка, ₽'])} ₽", f"{r['Рост выручки, %']}%")
    c3.metric("Продажи", f"{fmt(r['Продажи, шт'])} шт", f"{r['Рост продаж, %']}%")
    c2.metric("Товары с прод.", f"{fmt(r['Товары с прод.'])} шт", f"{r['Рост тов. с прод, %']}%")
    c4.metric("Выр/товар", f"{fmt(r['Сред. выручка/товар, ₽'])} ₽", f"{r['Рост выр/товар, %']}%")
    c5.metric("Ср. чек", f"{fmt(r['Средний чек, ₽'])} ₽", f"{r['Рост чека, %']}%")

    st.write("")

    st.markdown("##### 🕵️‍♂️ Анализ конкуренции (По продавцам)")
    cm1, cm2, cm3, cm4, cm5 = st.columns(5)
    cm1.metric("Конкуренция на рынке", mon['status'])
    cm2.metric("Наличие лидера", mon['leader'])
    cm3.metric("Индекс HHI", int(mon['hhi']))
    cm4.metric("Доля лидера (CR1)", f"{mon['cr1']}%")
    cm5.metric("Доля ТОП-5 (CR5)", f"{mon['cr5']}%")

    st.write("")

    st.markdown("##### 🔗 Дополнительные показатели")
    a1, a2, a3, a4, a5 = st.columns(5)
    a1.metric("Пик сезона", season)
    a2.metric("🥇 Ценовой карман №1", pockets[0])
    a3.metric("🥈 Ценовой карман №2", pockets[1])
    a4.metric("🥉 Ценовой карман №3", pockets[2])
    a5.empty()

st.divider()

# --- 4. СВОДНАЯ ТАБЛИЦА ---
if st.session_state.history:
    history_df = pd.DataFrame(st.session_state.history)

    col_t, col_csv, col_cl = st.columns([4, 1, 1])
    col_t.subheader("📊 Сводная таблица сравнения")

    csv_data = history_df.to_csv(index=False).encode('utf-8-sig')
    col_csv.download_button("📥 Скачать CSV", csv_data, 'comparison.csv', 'text/csv', use_container_width=True)

    if col_cl.button("🗑️ Очистить", use_container_width=True):
        st.session_state.history = []
        st.session_state.last_search = None
        st.rerun()

    display_df = history_df.copy()
    num_cols = ["Выручка, ₽", "Товары с прод.", "Продажи, шт", "Сред. выручка/товар, ₽", "Средний чек, ₽"]
    for col in num_cols:
        display_df[col] = display_df[col].apply(lambda x: f"{int(x):,}".replace(",", " "))

    growth_cols = [c for c in display_df.columns if "%" in c and "Доля" not in c]
    for col in growth_cols:
        display_df[col] = display_df[col].apply(lambda x: f"{x}%")

    st.dataframe(display_df, use_container_width=True, hide_index=True)

    st.divider()

    st.subheader("📈 Визуальное сравнение")
    exclude_cols = ["МП", "Категория", "Конкуренция на рынке", "Наличие лидера", "Лучший месяц", "Карман №1",
                    "Карман №2", "Карман №3"]
    metrics_list = [c for c in history_df.columns if c not in exclude_cols]

    default_index = metrics_list.index("Выручка, ₽") if "Выручка, ₽" in metrics_list else 0
    selected_metric = st.selectbox("Показатель для графика:", metrics_list, index=default_index)

    history_df['label'] = history_df['МП'] + ": " + history_df['Категория']
    fig = px.bar(
        history_df, x="label", y=selected_metric, color=selected_metric,
        text_auto='.2s', color_continuous_scale="Viridis", title=f"Сравнение по: {selected_metric}"
    )
    fig.update_layout(xaxis_title="", yaxis_title=selected_metric, xaxis_tickangle=-45)
    st.plotly_chart(fig, use_container_width=True)

# --- 6. СПРАВКА ---
st.divider()
with st.expander("ℹ️ Справка: Описание и формулы расчета метрик"):
    st.markdown("""
    ### 💰 Финансовые показатели
    * **Выручка (₽):** Выкупы в рублях за месяц (`revenue_estimated`). Если данных нет (например, на OZ), берется выручка (`revenue`).
    * **Продажи (шт):** Выкупы в штуках за месяц (`sales_estimated`). Если их нет, берутся продажи (`sales`).
    * **Товары с продажами:** Количество уникальных карточек товара, у которых была хотя бы одна продажа за месяц.
    * **Сред. выручка/товар (₽):** `Выручка ÷ Товары с продажами`. 
    * **Средний чек (₽):** `Выручка ÷ Продажи`.

    ### 🕵️‍♂️ Анализ монополии и конкуренции
    Расчет производится на основе данных по первым 200 продавцам (селлерам) в категории за выбранный месяц.
    * **Конкуренция на рынке:** 
        * **✅ Слабая:** HHI < 500. Рынок свободен.
        * **📊 Умеренная:** 500 < HHI < 600. Начинают формироваться лидеры.
        * **⚠️ Высокая:** HHI > 600 или CR5 > 40. Категория перегрета сильными брендами.
        * **🚨 Монополия:** Доля одного продавца больше 30%.
    * **Наличие лидера:**
        * **Монополист:** Доля Топ-1 больше 30%.
        * **Есть (Один):** Топ-1 больше Топ-2 в 2 и более раз.
        * **Два лидера:** Топ-2 больше Топ-3 в 2 и более раз (дуополия).
    * **Индекс HHI (Индекс Херфиндаля-Хиршмана):** Экономический показатель концентрации рынка. Считается как сумма квадратов рыночных долей (в процентах) всех продавцов в категории. 
    * **Доля лидера (CR1):** Процент всей выручки категории, который забирает себе продавец №1. 
    * **Доля ТОП-5 (CR5):** Если 5 крупнейших селлеров суммарно забирают более 40% рынка, конкуренция автоматически признается высокой.

    ### 🔗 Дополнительные показатели (Ценовые карманы считаются для всех маркетплейсов, сезонность только для WB)
    * **Пик сезона:** Исторически лучший месяц в категории с максимальной выручкой.
    * **Карман №1, №2, №3:** Топ-3 самых выгодных ценовых диапазона. 
        Итоговый коэффициент = Доля выручки кармана * 0,4 + Эффективность товара * 0,3 + Упущенная выручка * 0,15 + Средний чек * 0,15.
    """)

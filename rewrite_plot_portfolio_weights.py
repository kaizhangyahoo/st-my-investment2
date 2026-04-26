import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
import pandas as pd

def plot_portfolio_weights(df, weights: list, exchange_rate: dict):
    company_list = df['Market']
    # calculate cost in GBP if df['Currency'] is USD, use exchange_rate['GBPUSD=X'], else if EUR use exchange_rate['GBPEUR=X']
    df['Cost in GBP'] = df.apply(
        lambda row: row['Cost/Proceeds'] / exchange_rate['GBPUSD=X'] 
        if row['Currency'] == 'USD' else (row['Cost/Proceeds'] / exchange_rate['GBPEUR=X'] 
        if row['Currency'] == 'EUR' else row['Cost/Proceeds']), axis=1)
    

    fig = make_subplots(rows=1, cols=2, specs=[[{"type": "domain"}, {"type": "domain"}]]) # specs explained in https://plotly.com/python/subplots/
    fig.add_trace(go.Pie(
            labels = company_list,
            values = df['Market Value GBP'],
            pull = weights, 
            name = "Current Position",
        ), 1, 1)
    fig.add_trace(go.Pie(
            labels = company_list,
            values = abs(df['Cost in GBP']),
            pull = weights, 
            name = "Investment",
        ), 1, 2)
    fig.update_layout(
            title_text="Current position and total investment on each instrument",
            width=1000, 
            height=800,
            showlegend=False)
    return fig
# annotations=[dict(text='Current position', x=0.18, y=0.5, font_size=20, showarrow=False),
#              dict(text='£ invested', x=0.82, y=0.5, font_size=20, showarrow=False)])


def plot_cashflow(net_cashflow: dict):
        # 1. Define the Data
    
    y_categories = ['Dividend', 'Cash Interest - Platform Cost', 'Share Dealing Commissions', 'SDRT']
    x_values = []

    for i in y_categories:
        x_values.append(net_cashflow[i])

    y_categories.append('NET CASHFLOW')
    x_values.append(0)
    measure = ["relative", "relative", "relative", "relative", "total"]

    # 2. Format Labels (Add +/- and £ signs)
    text_labels = [f"+£{val:,.2f}" if val > 0 else f"-£{abs(val):,.2f}" for val in x_values[:4]]
    text_labels.append(f"£{sum(x_values):,.2f}") # Explicit Label for the Total

    # 3. Create the Waterfall Chart
    fig = go.Figure(go.Waterfall(
        name = "Portfolio Cashflow",
        orientation = "h", # Horizontal orientation
        measure = measure,
        y = y_categories,  # Categories on Y-axis for horizontal
        x = x_values,      # Values on X-axis
        text = text_labels,
        textposition = "auto",
        
        # "Nano Banana" Styling
        connector = {"line": {"color": "rgba(255, 255, 255, 0.5)", "width": 1, "dash": "dot"}},
        increasing = {"marker": {"color": "#F4D03F"}}, # Banana Yellow for Income
        decreasing = {"marker": {"color": "#FF6F61"}}, # Soft Red for Expenses
        totals = {"marker": {"color": "#2ECC71"}}      # Green for Final Net Flow
    ))

    # 4. Apply Dark Theme Layout
    fig.update_layout(
        title = {
            'text': "<b>PORTFOLIO CASHFLOW (GBP)</b>",
            'y': 0.95,
            'x': 0.5,
            'xanchor': 'center',
            'yanchor': 'top',
            'font': {'size': 20, 'color': '#F4D03F'}
        },
        plot_bgcolor = "#121212",  # Dark Background
        paper_bgcolor = "#121212", # Dark Background
        font = dict(family="Arial, sans-serif", color="#E0E0E0"),
        showlegend = False,
        margin = dict(t=80, b=40, l=150, r=40),
        xaxis = dict(
            showgrid = False,
            zeroline = False,
            showticklabels = False, # Hide x-axis numbers for a cleaner widget
        ),
        yaxis = dict(
            type='category',
            showgrid = False,
            autorange="reversed" # To put 'Dividend' at the top
        )
    )

    return fig

def portfolio_value_over_time(df, account_id):
    fig_portfolio = px.line(
                df,
                x='Date',
                y='Portfolio Value (GBP)',
                title=f'Portfolio Value Over Time (Account: {account_id})',
                labels={'Portfolio Value (GBP)': 'Value (£)'},
            )
    fig_portfolio.update_traces(line_color='#00C853', line_width=2)
    fig_portfolio.update_layout(
        hovermode='x unified',  
        yaxis_tickformat=',.0f',
        yaxis_tickprefix='£'
    )
    return fig_portfolio

def pie_chart_equity_by_currency(USD_market_value_in_gbp, EUR_market_value_in_gbp, GBP_market_value_in_gbp, Total_market_value_gbp):
    fig = px.pie(
        names=['USD', 'EUR', 'GBP'],
        values=[USD_market_value_in_gbp, EUR_market_value_in_gbp, GBP_market_value_in_gbp],
        title=f'Portfolio Currency Breakdown (Total Market Value: £{Total_market_value_gbp:,.2f})'
    )
    return fig


def ticker_price_chart_with_trades(df_ohlc, df_trades, ticker: str, currency: str = ""):
    """Create a line chart of close price with buy/sell trade markers.

    Args:
        df_ohlc: OHLC DataFrame with columns ['Date', 'close'] (other cols ignored)
        df_trades: Trade history DataFrame with columns ['Date', 'Direction', 'Price', 'Quantity']
        ticker: The ticker symbol (used in the title)
        currency: The currency of the price (e.g. 'USD', 'GBP')
    """
    fig = go.Figure()

    # ── Close price line with subtle fill ──
    fig.add_trace(
        go.Scatter(
            x=df_ohlc['Date'],
            y=df_ohlc['close'],
            mode='lines',
            line=dict(color='#64B5F6', width=2.5),
            fill='tozeroy',
            fillcolor='rgba(100, 181, 246, 0.08)',
            name='Close Price',
            hovertemplate='%{x|%Y-%m-%d}<br>Close: %{y:,.2f}<extra></extra>',
        )
    )

    # ── Buy markers ──
    buys = df_trades[df_trades['Direction'].str.upper() == 'BUY']
    if not buys.empty:
        fig.add_trace(
            go.Scatter(
                x=buys['Date'],
                y=buys['Price'],
                mode='markers+text',
                marker=dict(
                    symbol='triangle-up',
                    size=14,
                    color='#00E676',
                    line=dict(width=1.5, color='white'),
                ),
                text=[f"BUY {q}" for q in buys['Quantity']],
                textposition='top center',
                textfont=dict(size=10, color='#00E676'),
                name='Buy',
                hovertemplate=(
                    '<b>BUY</b><br>'
                    'Date: %{x|%Y-%m-%d}<br>'
                    'Price: %{y:,.2f}<br>'
                    '<extra></extra>'
                ),
            )
        )

    # ── Sell markers ──
    sells = df_trades[df_trades['Direction'].str.upper() == 'SELL']
    if not sells.empty:
        fig.add_trace(
            go.Scatter(
                x=sells['Date'],
                y=sells['Price'],
                mode='markers+text',
                marker=dict(
                    symbol='triangle-down',
                    size=14,
                    color='#FF5252',
                    line=dict(width=1.5, color='white'),
                ),
                text=[f"SELL {q}" for q in sells['Quantity']],
                textposition='bottom center',
                textfont=dict(size=10, color='#FF5252'),
                name='Sell',
                hovertemplate=(
                    '<b>SELL</b><br>'
                    'Date: %{x|%Y-%m-%d}<br>'
                    'Price: %{y:,.2f}<br>'
                    '<extra></extra>'
                ),
            )
        )

    # ── Layout ──
    currency_label = f" ({currency})" if currency else ""
    fig.update_layout(
        title={
            'text': f'<b>{ticker} – Price History & Trades</b>',
            'y': 0.97,
            'x': 0.5,
            'xanchor': 'center',
            'yanchor': 'top',
            'font': {'size': 18, 'color': '#F4D03F'},
        },
        plot_bgcolor='#1a1a2e',
        paper_bgcolor='#1a1a2e',
        font=dict(family='Arial, sans-serif', color='#E0E0E0'),
        hovermode='x unified',
        legend=dict(
            orientation='h',
            yanchor='bottom',
            y=1.02,
            xanchor='right',
            x=1,
            font=dict(size=12, color='#FFFFFF'),
            bgcolor='rgba(40, 40, 70, 0.85)',
            bordercolor='rgba(255, 255, 255, 0.3)',
            borderwidth=1,
        ),
        margin=dict(t=70, b=40, l=60, r=30),
        height=500,
        xaxis=dict(gridcolor='rgba(255,255,255,0.08)', showgrid=True),
        yaxis=dict(
            title=f'Price{currency_label}',
            gridcolor='rgba(255,255,255,0.08)',
            showgrid=True,
        ),
    )

    return fig




def t212_portfolio_value_over_time(df_all_trades, market_values):
    dates = market_values.index.normalize()  # strip time component
    values = market_values['total_value']

    fig = go.Figure()

    # Portfolio value line
    fig.add_trace(go.Scatter(
        x=dates, y=values,
        mode='lines',
        name='Portfolio Value (GBP)',
        line=dict(color='royalblue', width=2),
    ))

    # Trade markers — look up portfolio value on each trade date
    buys = df_all_trades[df_all_trades['Side'] == 'BUY']
    sells = df_all_trades[df_all_trades['Side'] == 'SELL']

    for label, subset, color, symbol in [
        ('Buy',  buys,  'green', 'triangle-up'),
        ('Sell', sells, 'red',   'triangle-down'),
    ]:
        # Match trade dates to portfolio value; skip if date not in index
        trade_dates = subset['Date'].dt.normalize()
        matched_values = market_values['total_value'].reindex(trade_dates).dropna()

        if not matched_values.empty:
            # Build hover text
            hover = []
            for d in matched_values.index:
                trades_on_date = subset[subset['Date'].dt.normalize() == d]
                parts = [f"{row['Ticker_T212']}: {abs(row['Signed_Qty']):.2f} @ {row['Price']:.2f}"
                        for _, row in trades_on_date.iterrows()]
                hover.append(f"{label}<br>{d.strftime('%Y-%m-%d')}<br>" + "<br>".join(parts))

            fig.add_trace(go.Scatter(
                x=matched_values.index.normalize(),
                y=matched_values.values,
                mode='markers',
                name=label,
                marker=dict(color=color, size=10, symbol=symbol, line=dict(width=1, color='white')),
                text=hover,
                hoverinfo='text+y',
            ))

    fig.update_layout(
        title='Portfolio Value Over Time',
        xaxis_title='Date',
        yaxis_title='Value (GBP)',
        xaxis=dict(tickformat='%Y-%m-%d'),
        yaxis=dict(tickprefix='£', tickformat=',.0f'),
        hovermode='closest',
        template='plotly_dark',
        legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1),
    )

    return fig

    


def portfolio_vs_benchmarks(df_portfolio, benchmark_values: dict):
    """Plot portfolio value vs pre-calculated benchmark simulations.

    Args:
        df_portfolio: DataFrame with columns ['Date', 'Portfolio Value (GBP)']
        benchmark_values: dict of {label: DataFrame} where each DF has ['Date', 'Value']
    """
    fig = go.Figure()

    # ── Portfolio line (actual £ values) ──
    df_p = df_portfolio.sort_values('Date').copy()
    df_p['Date'] = pd.to_datetime(df_p['Date'])

    fig.add_trace(go.Scatter(
        x=df_p['Date'], y=df_p['Portfolio Value (GBP)'],
        mode='lines',
        name='My Portfolio',
        line=dict(color='#00E676', width=3),
        hovertemplate='%{x|%Y-%m-%d}<br>£%{y:,.0f}<extra>My Portfolio</extra>',
    ))

    # ── Benchmark lines ──
    benchmark_colors = {
        'S&P 500':    '#64B5F6',
        'Nasdaq 100': '#FF7043',
    }
    fallback_colors = ['#AB47BC', '#26C6DA', '#FFCA28', '#EF5350']
    color_idx = 0

    for label, df_bench_val in benchmark_values.items():
        if df_bench_val is None or df_bench_val.empty:
            continue

        color = benchmark_colors.get(label, fallback_colors[color_idx % len(fallback_colors)])
        color_idx += 1

        fig.add_trace(go.Scatter(
            x=df_bench_val['Date'], y=df_bench_val['Value'],
            mode='lines',
            name=f'If bought {label}',
            line=dict(color=color, width=2, dash='dot'),
            hovertemplate='%{x|%Y-%m-%d}<br>£%{y:,.0f}<extra>' + label + '</extra>',
        ))

    # ── Layout ──
    fig.update_layout(
        title={
            'text': '<b>PORTFOLIO vs "WHAT IF" BENCHMARKS</b>',
            'y': 0.96, 'x': 0.5,
            'xanchor': 'center', 'yanchor': 'top',
            'font': {'size': 20, 'color': '#F4D03F'},
        },
        plot_bgcolor='#1a1a2e',
        paper_bgcolor='#1a1a2e',
        font=dict(family='Arial, sans-serif', color='#E0E0E0'),
        hovermode='x unified',
        legend=dict(
            orientation='h', yanchor='bottom', y=1.02,
            xanchor='right', x=1,
            font=dict(size=13, color='#FFFFFF'),
            bgcolor='rgba(40, 40, 70, 0.85)',
            bordercolor='rgba(255, 255, 255, 0.3)',
            borderwidth=1,
        ),
        margin=dict(t=80, b=50, l=60, r=30),
        height=550,
        xaxis=dict(gridcolor='rgba(255,255,255,0.08)', showgrid=True,
                   title='Date'),
        yaxis=dict(gridcolor='rgba(255,255,255,0.08)', showgrid=True,
                   title='Value (£)', tickprefix='£', tickformat=',.0f'),
    )

    return fig

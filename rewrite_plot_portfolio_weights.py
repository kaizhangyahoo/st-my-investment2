import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots

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
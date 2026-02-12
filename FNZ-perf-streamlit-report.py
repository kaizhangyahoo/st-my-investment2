import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots


st.title('FNZ Vanguard APIs Monthly Performance Report')
# create a file uploader
uploaded_file = st.file_uploader("upload fnz performance report", type=['csv'])
if uploaded_file is not None:
    try:
        df = pd.read_csv(uploaded_file)
        # df['date'] = pd.to_datetime(df['Date'] + ' ' + df['Hour'], format='%d/%m/%Y %I:%M:%S %p')
        df['date'] = pd.to_datetime(df['Date'] + ' ' + df['Hour'], format='%d/%m/%y %I:%M:%S %p')
    except Exception as e:
        print(e)
        st.write(f'Invalid file, {e}')

    df['path'] = df['facet'].str.extract(r'WebTransaction/ASP/api/distribution/v3/(.*)')
    df['service'] = df['path'].str.split('/').str[0]

    # some service might be na after that, fillna with last string of facet
    df['service'] = df['service'].fillna(df['facet'].str.split('/').str[-1])

    # create 2 tabs
    tab1, tab2  = st.tabs(["Performance", "SLA"])

    # TAB 1
    with tab1:

        st.write(f"There are a total of {df['service'].nunique()} services in the spreadsheet of which")
        st.header("Top 10 most hit services are:")
        busy_svc = df.groupby('service').agg(total_counts = ("RecordCount", "sum"), p95_avg = ("p95 (in ms)", "mean")).sort_values(by='total_counts', ascending=False).head(10)
        st.dataframe(busy_svc)

        st.write("Pick a service to check its performance")

        selected_service = st.selectbox('Select service', busy_svc.index)
        selected_df_hourly = df[df['service'] == selected_service]
        selected_df_daily = selected_df_hourly.resample('D', on='date').agg({'RecordCount': 'sum', 'p95 (in ms)': 'mean'})
        list_of_facets = selected_df_hourly['facet'].unique()
        markdown_list_of_facets = "\n".join([f"- {item}" for item in list_of_facets])
        st.write("Related endpoints are:")
        st.markdown(markdown_list_of_facets)

        fig = make_subplots(specs=[[{"secondary_y": True}]])
        fig.add_trace(go.Scatter(x=selected_df_daily.index, y=selected_df_daily['RecordCount'], mode='lines', name='Total Hits'), secondary_y=False)
        fig.add_trace(go.Scatter(x=selected_df_daily.index, y=selected_df_daily['p95 (in ms)'], mode='lines', name='P95'), secondary_y=True)
        fig.update_layout(title_text=f'{selected_service} API performance of the month')
        # Set y-axes titles
        fig.update_yaxes(title_text="RecordCount", secondary_y=False)
        fig.update_yaxes(title_text="p95 (in ms)", secondary_y=True)
        st.plotly_chart(fig)

        svc_max_date = selected_df_daily[selected_df_daily['RecordCount'] == selected_df_daily.RecordCount.max()].index
        df_busiest_day_for_input = df[(df['date'].dt.date == svc_max_date[0].date()) & (df['service'] == selected_service)]
        df_busiest_day_for_input_hourly = df_busiest_day_for_input.groupby('date').agg({'RecordCount': 'sum', 'p95 (in ms)': 'mean'})
        fig = make_subplots(specs=[[{"secondary_y": True}]])
        fig.add_trace(go.Scatter(x=df_busiest_day_for_input_hourly.index, y=df_busiest_day_for_input_hourly['RecordCount'], mode='lines', name='Total Hits'), secondary_y=False)
        fig.add_trace(go.Scatter(x=df_busiest_day_for_input_hourly.index, y=df_busiest_day_for_input_hourly['p95 (in ms)'], mode='lines', name='P95'), secondary_y=True)    
        fig.update_layout(title_text=f'{selected_service} API was busiest on {svc_max_date[0].date()}, below is an hourly chart of how it performed on that day')
        # Set y-axes titles
        fig.update_yaxes(title_text="RecordCount", secondary_y=False)
        fig.update_yaxes(title_text="p95 (in ms)", secondary_y=True)
        st.plotly_chart(fig)
        
        st.header("Top 10 worst performing services")
        bad_svc = df.groupby('service').agg(total_counts = ("RecordCount", "sum"), p95_avg = ("p95 (in ms)", "mean")).sort_values(by='p95_avg', ascending=False).head(10)
        st.dataframe(bad_svc)

        st.write("Pick a service to check its performance")

        selected_bad_service = st.selectbox('Select service', bad_svc.index)
        selected_bad_hourly = df[df['service'] == selected_bad_service]
        selected_bad_daily = selected_bad_hourly.resample('D', on='date').agg({'RecordCount': 'sum', 'p95 (in ms)': 'mean'})
        list_of_bad_facets = selected_bad_hourly['facet'].unique()
        markdown_list_of_facets = "\n".join([f"- {item}" for item in list_of_bad_facets])
        st.write("Related endpoints are:")
        st.markdown(markdown_list_of_facets)

        fig = make_subplots(specs=[[{"secondary_y": True}]])
        fig.add_trace(go.Scatter(x=selected_bad_daily.index, y=selected_bad_daily['p95 (in ms)'], mode='lines', name='P95'), secondary_y=False)
        fig.add_trace(go.Scatter(x=selected_bad_daily.index, y=selected_bad_daily['RecordCount'], mode='lines', name='Total Hits'), secondary_y=True)
        fig.update_layout(title_text=f'{selected_bad_service} API performance of the month')
        # Set y-axes titles
        fig.update_yaxes(title_text="RecordCount", secondary_y=True)
        fig.update_yaxes(title_text="p95 (in ms)", secondary_y=False)
        st.plotly_chart(fig)

        svc_worst_date = selected_bad_daily[selected_bad_daily['p95 (in ms)'] == selected_bad_daily['p95 (in ms)'].max()].index
        df_worst_day_for_input = df[(df['date'].dt.date == svc_worst_date[0].date()) & (df['service'] == selected_bad_service)]
        df_worst_day_for_input_hourly = df_worst_day_for_input.groupby('date').agg({'RecordCount': 'sum', 'p95 (in ms)': 'mean'})
        fig = make_subplots(specs=[[{"secondary_y": True}]])
        fig.add_trace(go.Scatter(x=df_worst_day_for_input_hourly.index, y=df_worst_day_for_input_hourly['p95 (in ms)'], mode='lines', name='P95'), secondary_y=True)
        fig.add_trace(go.Scatter(x=df_worst_day_for_input_hourly.index, y=df_worst_day_for_input_hourly['RecordCount'], mode='lines', name='Total Hits'), secondary_y=False)
        fig.update_layout(title_text=f'{selected_bad_service} API was worst on {svc_worst_date[0].date()}, below is an hourly chart of how it performed on that day')
        # Set y-axes titles
        fig.update_yaxes(title_text="RecordCount", secondary_y=False)
        fig.update_yaxes(title_text="p95 (in ms)", secondary_y=True)
        st.plotly_chart(fig)

    # TAB 2
    with tab2:

        df_SLA = pd.read_csv("FNZlatencySLA.csv") # TODO: what's the alternative import method
        df = pd.merge(df, df_SLA, left_on="facet", right_on="FNZ DISTRIBUTION API", how="left")
        # if no SLA defined for that api, assign 10000 to ignore it
        df["SLA"] = df["SLA"].fillna(10000)
        df_sla_breached = df[df['SLA']*1200 < df['p95 (in ms)']]
        st.write(f"Total number of queries' P95 that breached SLA: {df_sla_breached['RecordCount'].sum()}")
        # create a download button to download df_sla_breached dataframe as a csv
        st.write("Download the breached SLA data")

        # Create a download button to download df_sla_breached dataframe as a CSV
        csvfile = df_sla_breached.to_csv(index=False)
        st.download_button(
            label="Download breached SLA data as CSV",
            data=csvfile,
            file_name='breached_sla_data.csv',
            mime='text/csv',
        )


        # st.write("eg. following services have their P95 breached SLA")
        # st.dataframe(df_sla_breached[df_sla_breached['service']=='accountpayments'])

        #st.dataframe(df_sla_breached.groupby('service').agg({'RecordCount': 'sum'}))


        df_sla_breached_daily_heatmap = df_sla_breached.groupby(df_sla_breached['Date']).agg({'RecordCount': 'sum'})

        if len(df_sla_breached_daily_heatmap.index) < 35: #TODO: to calculate 35 in future
            dates_matrix = np.append(df_sla_breached_daily_heatmap.index, np.repeat(np.nan, 35-len(df_sla_breached_daily_heatmap.index)))
            dates_matrix = dates_matrix.reshape(5, 7)   
            record_counts_matrix = np.append(df_sla_breached_daily_heatmap['RecordCount'], np.repeat(np.nan, 35-len(df_sla_breached_daily_heatmap.index)))
            record_counts_matrix = record_counts_matrix.reshape(5, 7)

        st.write("Amount of queries with their P95 that breached SLA")
        st.write()

        fig = go.Figure(data=go.Heatmap(
                    z=record_counts_matrix,
                    x=['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'],
                    y=['Week 1', 'Week 2', 'Week 3', 'Week 4', 'Week 5'],
                    colorscale='Viridis'))

    # Add annotations for the dates
        annotations = []
        for i in range(dates_matrix.shape[0]):
            for j in range(dates_matrix.shape[1]):
                annotations.append(
                    go.layout.Annotation(
                        text=dates_matrix[i, j],
                        x=['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'][j],
                        y=['Week 1', 'Week 2', 'Week 3', 'Week 4', 'Week 5'][i],
                        showarrow=False,
                        font=dict(color="white")
                    )
                )

        # Update layout for better visualization
        fig.update_layout(
            title="Heatmap of all SLA breached days",
            xaxis_nticks=7,
            yaxis_nticks=5,
            annotations=annotations,
            # clickmode='event+select'
        )
        # fig.data[0].on_click(lambda trace, points, state: st.write(f"Clicked on: {points}"))
        st.plotly_chart(fig)

        selected_date = st.date_input("Date", value=pd.to_datetime("2025-01-01")) # TODO: to calculate the date range in future and limit valid dates
        df_select_sla_breach = df_sla_breached[df_sla_breached['date'].dt.date == selected_date]
        st.dataframe(df_select_sla_breach[['date', 'service', 'RecordCount', 'p95 (in ms)', 'SLA', 'FNZ DISTRIBUTION API']])
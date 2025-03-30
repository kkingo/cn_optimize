#!/usr/bin/env python
import datetime
import dash
from dash import dcc
from dash import html
from dash.dependencies import Input, Output, State
import plotly.graph_objects as go
import networkx as nx
from flask import request
import logging
import itertools
import json
import socket
import threading
import requests

# Import time for other usage if needed
import time

# Set Flask log level
log = logging.getLogger('werkzeug')
log.setLevel(logging.WARNING)

# Initialize Dash app
app = dash.Dash(__name__)

# Global data structures (unchanged for visualization)
transfer_data = {
    0: {},  # optimized=0
    1: {}   # optimized=1
}
time_usage_data = {
    0: [],  # optimized=0
    1: []   # optimized=1
}
bandwidth_data = {
    0: [],  # optimized=0
    1: []   # optimized=1
}

# Dialog / rotating controls
dialog_visible = False
dialog_hide_time = None
rotating_nodes = set()

# Edge colors
edge_colors = {
    (1, 2): 'red',
    (2, 3): 'green',
    (2, 4): 'blue',
    (3, 4): 'purple'
}

# Node labels
node_labels = {
    1: 'download',
    2: 'preprocess',
    3: 'training',
    4: 'test'
}

# Rotation symbols
rotation_symbols = ['circle', 'circle-open', 'circle-cross', 'circle-x', 'circle-dot', 'circle-open-dot']
rotation_cycle = itertools.cycle(rotation_symbols)

# We remove old "running" logic and data_index usage
# Add new global vars for TCP server
client_connection = None

# Load local JSON data if still needed; you can remove it entirely if not used
# with open('data.json', 'r') as f:
#     json_data = json.load(f)

###########################################################################
#                         TCP SERVER SETUP
###########################################################################

def run_tcp_server():
    """Run a simple TCP server to accept a single client connection."""
    global client_connection
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.bind(("0.0.0.0", 9999))
    server_socket.listen(1)
    print("TCP server is listening on port 9999...")
    while True:
        conn, addr = server_socket.accept()
        print(f"New client connected from {addr}")
        client_connection = conn
        # If you need to handle multiple clients, store them in a list or dict
        # For simplicity, we only handle one client in this demo


###########################################################################
#                         FLASK ROUTE /update_data
###########################################################################

@app.server.route('/update_data', methods=['POST'])
def update_data():
    global transfer_data, time_usage_data, dialog_visible, dialog_hide_time, rotating_nodes, bandwidth_data
    data = request.get_json()
    optimized = data.get('optimized', 1)
    from_node = int(data['from'])
    to_node = int(data['to'])

    if optimized == 2:
        latency = 7
        dialog_visible = True
        dialog_hide_time = datetime.datetime.now() + datetime.timedelta(seconds=latency)
        return '', 200
    elif optimized == 3:
        dialog_visible = False
        dialog_hide_time = None
        return '', 200
    elif optimized == 4:
        # rotating_nodes.add(from_node)
        return '', 200
    elif optimized == 5:
        # rotating_nodes.discard(from_node)
        return '', 200

    edge_key = (from_node, to_node)
    progress = data.get('progress', 0)
    progress = max(0, min(progress, 1))  # keep progress between 0 and 1
    timeusage = data.get('timeusage', 0)


    transfer_data[optimized][edge_key] = {
        'bandwidth': data.get('bandwidth'),
        'latency': data.get('latency'),
        'progress': progress
    }

    existing_edges = [item['edge_key'] for item in time_usage_data[optimized]]
    if edge_key not in existing_edges:
        time_usage_data[optimized].append({
            'edge_key': edge_key,
            'timeusage': timeusage
        })
    else:
        for item in time_usage_data[optimized]:
            if item['edge_key'] == edge_key:
                item['timeusage'] = timeusage
                break

    if optimized in [0, 1] and from_node == 1:
        bandwidth = data.get('bandwidth', 0)
        timestamp = data.get('timeusage', 0)
        bandwidth_data[optimized].append((timestamp, bandwidth))

    return '', 200

###########################################################################
#                         PLOTLY GRAPHING FUNCTIONS
###########################################################################

def create_custom_directed_graph(optimized, interval_count):
    G = nx.DiGraph()
    for node_id, label in node_labels.items():
        G.add_node(node_id, label=label)
    G.add_edges_from([
        (1, 2),
        (2, 3),
        (2, 4),
        (3, 4)
    ])

    x_distance = 1 / 2
    pos = {
        1: (0, 0.5),
        2: (x_distance, 0.5),
        3: (2 * x_distance, 0.7),
        4: (2 * x_distance, 0.3)
    }

    y3 = pos[3][1]
    y4 = pos[4][1]
    y2 = pos[2][1]
    assert (y3 + y4) / 2 == y2, "Node 3 and 4 mid y should match node 2 y"

    edge_traces = []
    annotations = []
    current_transfer_data = transfer_data.get(optimized, {})

    for edge in G.edges():
        x0, y0 = pos[edge[0]]
        x1, y1 = pos[edge[1]]
        edge_key = (edge[0], edge[1])

        edge_color = edge_colors.get(edge_key, '#888')

        transfer = current_transfer_data.get(edge_key)
        if transfer:
            progress = transfer.get('progress', 0)
            progress = max(0, min(progress, 1))

            if progress >= 1.0:
                edge_trace_full = go.Scatter(
                    x=[x0, x1],
                    y=[y0, y1],
                    line=dict(width=6, color=edge_color),
                    mode='lines',
                    hoverinfo='none'
                )
                edge_traces.append(edge_trace_full)
            else:
                x_progress = x0 + progress * (x1 - x0)
                y_progress = y0 + progress * (y1 - y0)

                edge_trace_progress = go.Scatter(
                    x=[x0, x_progress],
                    y=[y0, y_progress],
                    line=dict(width=6, color=edge_color),
                    mode='lines',
                    hoverinfo='none'
                )
                edge_traces.append(edge_trace_progress)

                edge_trace_remaining = go.Scatter(
                    x=[x_progress, x1],
                    y=[y_progress, y1],
                    line=dict(width=2, color='#888'),
                    mode='lines',
                    hoverinfo='none'
                )
                edge_traces.append(edge_trace_remaining)

            annotations.append(
                dict(
                    ax=x0,
                    ay=y0,
                    axref='x',
                    ayref='y',
                    x=x1,
                    y=y1,
                    xref='x',
                    yref='y',
                    showarrow=True,
                    arrowhead=2,
                    arrowsize=1,
                    arrowwidth=2,
                    arrowcolor='#888'
                )
            )
        else:
            edge_trace = go.Scatter(
                x=[x0, x1],
                y=[y0, y1],
                line=dict(width=2, color='#888'),
                mode='lines',
                hoverinfo='none'
            )
            edge_traces.append(edge_trace)
            annotations.append(
                dict(
                    ax=x0,
                    ay=y0,
                    axref='x',
                    ayref='y',
                    x=x1,
                    y=y1,
                    xref='x',
                    yref='y',
                    showarrow=True,
                    arrowhead=2,
                    arrowsize=1,
                    arrowwidth=2,
                    arrowcolor='#888'
                )
            )

    node_x = []
    node_y = []
    node_text = []
    node_textpositions = []
    node_symbols = []

    for node in G.nodes():
        x, y = pos[node]
        node_x.append(x)
        node_y.append(y)
        node_text.append(G.nodes[node]['label'])
        if node == 3:
            node_textpositions.append('top center')
        else:
            node_textpositions.append('bottom center')

        # If node is rotating, pick a symbol based on interval_count
        if node in rotating_nodes:
            symbol_index = (interval_count + node) % len(rotation_symbols)
            node_symbols.append(rotation_symbols[symbol_index])
        else:
            node_symbols.append('circle')

    node_trace = go.Scatter(
        x=node_x,
        y=node_y,
        mode='markers+text',
        text=node_text,
        textposition=node_textpositions,
        marker=dict(
            size=40,
            color='#FF5733',
            symbol=node_symbols
        ),
        hoverinfo='text',
        textfont=dict(size=12)
    )

    fig = go.Figure(data=edge_traces + [node_trace],
                    layout=go.Layout(
                        showlegend=False,
                        hovermode='closest',
                        margin=dict(l=20, r=20, t=20, b=20),
                        annotations=annotations,
                        xaxis=dict(
                            showgrid=False,
                            zeroline=False,
                            showticklabels=False,
                            range=[-0.1, 1.1]
                        ),
                        yaxis=dict(
                            showgrid=False,
                            zeroline=False,
                            showticklabels=False,
                            range=[0, 1]
                        ),
                        height=300,
                        plot_bgcolor='rgba(0,0,0,0)',
                        paper_bgcolor='rgba(0,0,0,0)',
                        shapes=[dict(
                            type='rect',
                            xref='paper',
                            yref='paper',
                            x0=0,
                            y0=0,
                            x1=1,
                            y1=1,
                            line=dict(color='gray', width=1)
                        )]
                    ))
    return fig

def create_combined_bar_chart(optimized):
    current_time_usage = time_usage_data.get(optimized, [])
    current_time_usage.sort(key=lambda x: (x['edge_key'][0], x['edge_key'][1]))

    bars = []
    all_edges = [
        (1, 2),
        (2, 3),
        (2, 4),
        (3, 4)
    ]
    timeusage_dict = {item['edge_key']: item['timeusage'] for item in current_time_usage}

    for edge_key in all_edges:
        timeusage = timeusage_dict.get(edge_key, 0)
        color = edge_colors.get(edge_key, '#888')
        hover_text = f"{node_labels[edge_key[0]]} -> {node_labels[edge_key[1]]}: {timeusage:.2f}s"
        legend_name = f"{node_labels[edge_key[0]]} -> {node_labels[edge_key[1]]}"

        bar = go.Bar(
            x=[timeusage],
            y=['Time Usage'],
            orientation='h',
            marker_color=color,
            text=[f"{timeusage:.2f}s"] if timeusage > 0 else [''],
            textposition='inside',
            hovertext=hover_text,
            hoverinfo='text',
            name=legend_name,
            width=0.5
        )
        bars.append(bar)

    x_axis_range = [0, 100]
    fig = go.Figure(data=bars)
    fig.update_layout(
        barmode='stack',
        xaxis_title='Time Usage (s)',
        yaxis=dict(showticklabels=False),
        margin=dict(l=20, r=20, t=20, b=20),
        height=150,
        xaxis=dict(range=x_axis_range),
        plot_bgcolor='rgba(0,0,0,0)',
        paper_bgcolor='rgba(0,0,0,0)',
        shapes=[dict(
            type='rect',
            xref='paper',
            yref='paper',
            x0=0,
            y0=0,
            x1=1,
            y1=1,
            line=dict(color='gray', width=1)
        )],
        legend=dict(
            title='Edges',
            orientation='h',
            yanchor='bottom',
            y=1.02,
            xanchor='center',
            x=0.5
        )
    )
    return fig

def create_bandwidth_line_chart():
    data_0 = bandwidth_data.get(0, [])
    data_1 = bandwidth_data.get(1, [])

    filtered_data_0 = []
    last_x_0 = None
    for (x, y) in data_0:
        if last_x_0 is None or x >= last_x_0:
            filtered_data_0.append((x, y))
            last_x_0 = x

    filtered_data_1 = []
    last_x_1 = None
    for (x, y) in data_1:
        if last_x_1 is None or x >= last_x_1:
            filtered_data_1.append((x, y))
            last_x_1 = x

    times_0 = [item[0] for item in filtered_data_0]
    bandwidths_0 = [item[1] for item in filtered_data_0]
    times_1 = [item[0] for item in filtered_data_1]
    bandwidths_1 = [item[1] for item in filtered_data_1]

    trace_0 = go.Scatter(
        x=times_0,
        y=bandwidths_0,
        mode='lines+markers',
        name='Regular'  # optimized=0
    )

    trace_1 = go.Scatter(
        x=times_1,
        y=bandwidths_1,
        mode='lines+markers',
        name='Optimized'  # optimized=1
    )

    fig = go.Figure(data=[trace_0, trace_1])
    fig.update_layout(
        title='Bandwidth Over Time',
        xaxis_title='Time',
        yaxis_title='Bandwidth (Mbps)',
        height=500,
        margin=dict(l=20, r=20, t=50, b=20),
        plot_bgcolor='rgba(0,0,0,0)',
        paper_bgcolor='rgba(0,0,0,0)',
        shapes=[dict(
            type='rect',
            xref='paper',
            yref='paper',
            x0=0,
            y0=0,
            x1=1,
            y1=1,
            line=dict(color='gray', width=1)
        )]
    )

    return fig

###########################################################################
#                           DASH LAYOUT
###########################################################################

app.layout = html.Div([
    dcc.Location(id='url', refresh=False),
    html.Div(id='dummy-output', style={'display': 'none'}),

    html.Div([
        html.Div([
            html.H3('ScalaCN optimized container networks', style={'textAlign': 'center', 'font-size': '18px'}),
            dcc.Graph(id='graph1'),
        ], style={'width': '48%', 'display': 'inline-block'}),

        html.Div([
            html.H3('Regular container networks', style={'textAlign': 'center', 'font-size': '18px'}),
            dcc.Graph(id='graph2'),
        ], style={'width': '48%', 'display': 'inline-block'}),
    ], style={'textAlign': 'center'}),

    html.Div([
        # The "Run" button now only sends data to the connected client
        html.Button('Run', id='run-button', n_clicks=0, style={'margin-right': '20px'}),
        html.H3('Time Usage Comparison', style={'textAlign': 'center', 'font-size': '18px', 'display': 'inline-block'}),
        dcc.Graph(id='bar1'),
        dcc.Graph(id='bar2'),
    ], style={'width': '100%', 'display': 'block', 'textAlign': 'center'}),

    html.Div([
        html.H3('Bandwidth Over Time', style={'textAlign': 'center', 'font-size': '18px'}),
        dcc.Graph(id='line-chart'),
    ], style={'width': '100%', 'display': 'block', 'textAlign': 'center'}),

    html.Div(
        id='modal-dialog',
        children=[
            html.Div(
                children=[
                    html.H2('ScalaCN 正在优化容器网络', style={'color': 'white'}),
                ],
                style={
                    'backgroundColor': '#111111',
                    'padding': '20px',
                    'borderRadius': '5px',
                    'textAlign': 'center'
                }
            )
        ],
        style={
            'position': 'fixed',
            'top': '0',
            'left': '0',
            'width': '100%',
            'height': '100%',
            'backgroundColor': 'rgba(0,0,0,0.5)',
            'display': 'none',
            'justifyContent': 'center',
            'alignItems': 'center',
            'zIndex': '1000'
        }
    ),

    dcc.Interval(id='interval', interval=1000, n_intervals=0)
])

###########################################################################
#              CALLBACKS - Remove old run logic, add new send data
###########################################################################

@app.callback(Output('dummy-output', 'children'),
              [Input('url', 'pathname')])
def reset_data(pathname):
    """Reset all data when URL changes or page refreshes."""
    global transfer_data, time_usage_data, bandwidth_data
    global dialog_visible, dialog_hide_time, rotating_nodes
    global client_connection

    transfer_data = {0: {}, 1: {}}
    time_usage_data = {0: [], 1: []}
    bandwidth_data = {0: [], 1: []}
    dialog_visible = False
    dialog_hide_time = None
    rotating_nodes = set()
    # We do not reset or close the TCP connection here, but you could if needed.

    return ''

@app.callback(
    Output('run-button', 'children'),
    [Input('run-button', 'n_clicks')]
)
def send_data_to_client(n_clicks):
    """When user clicks the Run button, send a message to the connected client."""
    global client_connection
    if n_clicks > 0:
        try:
            response = requests.get("http://127.0.0.1:30080/start")
            # Check if the request was successful (HTTP status code 200)
            if response.status_code == 200:
                return "Started Container Network"
            else:
                return f"Starting failed with status code: {response.status_code}"
        except Exception as e:
            print(f"backend error: {e}")
            return "Starting failed"
    return "Run"

@app.callback(
    [
        Output('graph1', 'figure'),
        Output('graph2', 'figure'),
        Output('bar1', 'figure'),
        Output('bar2', 'figure'),
        Output('modal-dialog', 'style'),
        Output('line-chart', 'figure')
    ],
    [Input('interval', 'n_intervals')]
)
def update_graph(n_intervals):
    """Update the graphs periodically based on the current global data."""
    global dialog_visible, dialog_hide_time

    # Check if modal should hide
    if dialog_visible:
        if dialog_hide_time and datetime.datetime.now() >= dialog_hide_time:
            dialog_visible = False
            dialog_hide_time = None

    # Simply create figures from current data
    fig1 = create_custom_directed_graph(optimized=1, interval_count=n_intervals)
    fig2 = create_custom_directed_graph(optimized=0, interval_count=n_intervals)
    bar1 = create_combined_bar_chart(optimized=1)
    bar2 = create_combined_bar_chart(optimized=0)
    line_chart = create_bandwidth_line_chart()

    # Set dialog visibility
    if dialog_visible:
        modal_style = {
            'position': 'fixed',
            'top': '0',
            'left': '0',
            'width': '100%',
            'height': '100%',
            'backgroundColor': 'rgba(0,0,0,0.5)',
            'display': 'flex',
            'justifyContent': 'center',
            'alignItems': 'center',
            'zIndex': '1000'
        }
    else:
        modal_style = {'display': 'none'}

    return fig1, fig2, bar1, bar2, modal_style, line_chart

###########################################################################
#                                MAIN
###########################################################################

if __name__ == '__main__':

    server_thread = threading.Thread(target=run_tcp_server, daemon=True)
    server_thread.start()
    print("TCP server thread started.")
    app.run_server(host='0.0.0.0', port=8888)

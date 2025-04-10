import plotly.graph_objs as go
import json
import plotly

def create_plot(title, x_data, y_data, y_label, line_color, plot_type='scatter'):
    trace = go.Bar(x=x_data, y=y_data, name=y_label, marker=dict(color=line_color)) if plot_type == 'bar' else \
            go.Scatter(x=x_data, y=y_data, mode='lines', name=y_label, line=dict(color=line_color))

    fig = go.Figure(data=[trace], layout=go.Layout(title=title, xaxis=dict(title="Time"), yaxis=dict(title=y_label)))
    return json.dumps(fig, cls=plotly.utils.PlotlyJSONEncoder)


def generate_all_plots(timestamps, temperatures, humidity, pressure, altitude, air_quality):
    """Generate JSON plots for all sensor data."""

    plots = {
        "temperature_plot": create_plot("Temperature Over Time", timestamps, temperatures, "Temperature (°C)", "red"),
        "humidity_plot": create_plot("Humidity Over Time", timestamps, humidity, "Humidity (%)", "blue"),
        "pressure_plot": create_plot("Pressure Over Time", timestamps, pressure, "Pressure (hPa)", "green"),
        "altitude_plot": create_plot("Altitude Over Time", timestamps, altitude, "Altitude (m)", "purple"),
        "air_quality_plot": create_plot("Air Quality Over Time", timestamps, air_quality, "Air Quality (PPM)", "orange")
    }

    return plots
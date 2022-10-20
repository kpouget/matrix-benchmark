import datetime
from collections import defaultdict

import plotly.graph_objs as go
import plotly.express as px
import pandas as pd
from dash import html

import matrix_benchmarking.plotting.table_stats as table_stats
import matrix_benchmarking.common as common

def default_get_metrics(entry, metric):
    return entry.results.metrics[metric]


class Plot():
    def __init__(self, metrics, name, title, y_title,
                 get_metrics=default_get_metrics,
                 filter_metrics=lambda entry, metrics: metrics,
                 as_timestamp=False,
                 get_legend_name=None,
                 show_metrics_in_title=False,
                 show_queries_in_title=False,
                 show_legend=True,
                 y_divisor=1,
                 higher_better=False,
                 ):
        self.name = name
        self.id_name = f"prom_overview_{''.join( c for c in self.name if c not in '?:!/;()' ).replace(' ', '_').lower()}"
        self.title = title
        self.metrics = metrics
        self.y_title = y_title
        self.y_divisor = y_divisor
        self.filter_metrics = filter_metrics
        self.get_metrics = get_metrics
        self.as_timestamp = as_timestamp
        self.get_legend_name = get_legend_name
        self.show_metrics_in_title = show_metrics_in_title
        self.show_queries_in_title = show_queries_in_title
        self.show_legend = show_legend
        self.threshold_key = self.id_name
        self.higher_better = higher_better

        table_stats.TableStats._register_stat(self)
        common.Matrix.settings["stats"].add(self.name)

    def do_hover(self, meta_value, variables, figure, data, click_info):
        return "nothing"

    def do_plot(self, ordered_vars, settings, setting_lists, variables, cfg):
        plot_title = self.title if self.title else self.name

        if self.show_metrics_in_title:
            metric_names = [
                list(metric.items())[0][0] if isinstance(metric, dict) else metric
                for metric in self.metrics.keys()
            ]
            plot_title += f"<br>{'<br>'.join(metric_names)}"

        if self.show_queries_in_title:
            queries_names = self.metrics.values()
            plot_title += f"<br>{'<br>'.join(queries_names)}"

        y_max = 0

        single_expe = sum(1 for _ in common.Matrix.all_records(settings, setting_lists)) == 1
        data_threshold = []
        threshold_status = defaultdict(list)

        data = []
        for entry in common.Matrix.all_records(settings, setting_lists):
            try:
                threshold_value = entry.results.thresholds.get(self.threshold_key) if self.threshold_key else None
            except AttributeError: threshold_value = None

            try: check_thresholds = entry.results.check_thresholds
            except AttributeError: check_thresholds = False

            for metric in self.metrics:
                metric_name, metric_query = list(metric.items())[0] if isinstance(metric, dict) else (metric, metric)

                for metric in self.filter_metrics(entry, self.get_metrics(entry, metric_name)):
                    if not metric: continue

                    x_values = [x for x, y in metric["values"]]
                    y_values = [float(y)/self.y_divisor for x, y in metric["values"]]

                    if self.get_legend_name:
                        legend_name, legend_group = self.get_legend_name(metric_name, metric["metric"])
                    else:
                        legend_name = metric["metric"].get("__name__", metric_name)
                        legend_group = None

                    if legend_group: legend_group = str(legend_group)
                    else: legend_group = None

                    if self.as_timestamp:
                        x_values = [datetime.datetime.fromtimestamp(x) for x in x_values]
                    else:
                        x_start = x_values[0]
                        x_values = [x-x_start for x in x_values]

                    y_max = max([y_max]+y_values)
                    if single_expe:
                        data.append(
                            go.Scatter(
                                x=x_values, y=y_values,
                                name=str(legend_name),
                                hoverlabel= {'namelength' :-1},
                                showlegend=self.show_legend,
                                legendgroup=legend_group,
                                legendgrouptitle_text=legend_group,
                                mode='markers+lines'))
                    else:
                        entry_version = ", ".join([f"{key}={entry.settings.__dict__[key]}" for key in variables])
                        for y_value in y_values:
                            data.append(dict(Version=entry_version,
                                             Metric=legend_name,
                                             Value=y_value))
                        if threshold_value:
                            if threshold_value.endswith("%"):
                                _threshold_pct = int(threshold_value[:-1]) / 100
                                _threshold_value = _threshold_pct * max(y_values)
                            else:
                                _threshold_value = threshold_value

                            data_threshold.append(dict(Version=entry_version,
                                                       Value=_threshold_value,
                                                       Metric=legend_name))
                        if threshold_value and check_thresholds:
                            status = "PASS"
                            if threshold_value.endswith("%"):
                                _threshold_pct = int(threshold_value[:-1]) / 100
                                _threshold_value = _threshold_pct * max(y_values)
                            else:
                                _threshold_value = float(threshold_value)

                            status = "PASS"
                            if self.higher_better:
                                test_passed = min(y_values) >= _threshold_value
                                if not test_passed:
                                    status = f"FAIL: {min(y_values):.2f} < threshold={threshold_value}"

                            else:
                                test_passed = max(y_values) <= _threshold_value
                                if not test_passed:
                                    status = f"FAIL: {max(y_values):.2f} > threshold={threshold_value}"

                            if threshold_value.endswith("%"):
                                status += f" (={_threshold_value:.2f})"

                            threshold_status[entry_version].append(status)

        if single_expe:
            fig = go.Figure(data=data)

            fig.update_layout(
                title=plot_title, title_x=0.5,
                yaxis=dict(title=self.y_title, range=[0, y_max*1.05]),
                xaxis=dict(title=None if self.as_timestamp else "Time (in s)"))
        else:
            df = pd.DataFrame(data).sort_values(by=["Version"])
            fig = px.box(df, x="Version", y="Value", color="Version")
            fig.update_layout(
                title=plot_title, title_x=0.5,
                yaxis=dict(title=self.y_title)
            )
            if data_threshold:
                df_threshold = pd.DataFrame(data_threshold).sort_values(by=["Version"])
                fig.add_scatter(name="Threshold",
                                x=df_threshold['Version'], y=df_threshold['Value'], mode='lines+markers',
                                marker=dict(color='red', size=15, symbol="triangle-up" if self.higher_better else "triangle-down"),
                                line=dict(color='brown', width=5, dash='dot'))

        msg = []
        for legend_name, status in threshold_status.items():
            total_count = len(status)
            pass_count = status.count("PASS")
            success = pass_count == total_count
            msg += [html.B(legend_name), ": ", html.B("PASSED" if success else "FAILED"), f" ({pass_count}/{total_count} success{'es' if pass_count > 1 else ''})"]
            failures = []
            for a_status in status:
                if a_status == "PASS": continue
                failures.append(html.Li(a_status))
            if failures:
                msg.append(html.Ul(failures))
            else:
                msg.append(html.Br())

        return fig, msg

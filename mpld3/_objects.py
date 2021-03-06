import abc
import uuid
import warnings
import base64
import io
import json
from collections import defaultdict

import jinja2

import numpy as np

from matplotlib.lines import Line2D
from matplotlib.image import imsave
from matplotlib.path import Path
import matplotlib as mpl

from ._utils import (color_to_hex, get_dasharray, get_d3_shape_for_marker,
                     path_data, collection_data)
from ._js import CONSTRUCT_SVG_PATH


class D3Base(object):
    """Abstract Base Class for D3js objects"""
    __metaclass__ = abc.ABCMeta

    # keep track of the number of children of each element:
    # this assists in generating unique ids for all HTML elements
    num_children_by_id = defaultdict(int)

    @staticmethod
    def generate_unique_id():
        return str(uuid.uuid4()).replace('-', '')

    def _initialize(self, parent=None, **kwds):
        # set attributes
        self.parent = parent
        for key, val in kwds.items():
            setattr(self, key, val)

        # create a unique element id
        if parent is None:
            self.elid = self.generate_unique_id()
        else:
            self.num_children_by_id[self.parent.elid] += 1
            self.elid = (self.parent.elid +
                         str(self.num_children_by_id[self.parent.elid]))

    def __getattr__(self, attr):
        if attr in ['fig', 'ax', 'figid', 'axid']:
            if hasattr(self, '_' + attr):
                return getattr(self, '_' + attr)
            elif self.parent is not None and self.parent is not self:
                return getattr(self.parent, attr)
        else:
            raise AttributeError("no attribute {0}".format(attr))

    @abc.abstractmethod
    def html(self):
        raise NotImplementedError()

    def style(self):
        return ''

    def zoom(self):
        return ''

    def __str__(self):
        return self.html()


class D3Figure(D3Base):
    """Class for representing a matplotlib Figure in D3js"""

    TEMPLATE = jinja2.Template("""
    {% if with_d3_import %}
    <script type="text/javascript" src="{{ d3_url }}"></script>
    {% endif %}

    {% if with_style %}
    <style>
      {% for ax in axes %}
        {{ ax.style() }}
      {% endfor %}
    </style>
    {% endif %}

    <div id='figure{{ figid }}'>
    {% if with_reset_button %}
      <button id='reset{{ figid }}'>Reset</button>
    {% endif %}
    </div>

    <script type="text/javascript">
    func{{ figid }} = function(figure){
        var figwidth = {{ fig.get_figwidth() }} * {{ fig.dpi }};
        var figheight = {{ fig.get_figheight() }} * {{ fig.dpi }};

        var canvas = figure.append('svg:svg')
                       .attr('width', figwidth)
                       .attr('height', figheight)
                       .attr('class', 'canvas')

        {% for ax in axes %}
         {{ ax.html() }}
        {% endfor %}
    }

    // set a timeout of 0 to allow d3.js to load
    setTimeout(function(){ func{{ figid }}(
                                d3.select('#figure{{ figid }}')) }, 0)
    </script>
    """)

    def __init__(self, fig):
        self._initialize(parent=None, _fig=fig, _ax=None)
        self._figid = self.elid
        self.axes = [D3Axes(self, ax) for ax in fig.axes]

    def html(self, d3_url="http://d3js.org/d3.v3.min.js",
             with_d3_import=True, with_style=True,
             with_reset_button=False):
        return self.TEMPLATE.render(figid=self.figid,
                                    fig=self.fig,
                                    axes=self.axes,
                                    d3_url=d3_url,
                                    with_d3_import=with_d3_import,
                                    with_style=with_style,
                                    with_reset_button=with_reset_button)


class D3Axes(D3Base):
    """Class for representing a matplotlib Axes in D3js"""

    STYLE = jinja2.Template("""
    div#figure{{ figid }}
    .axes{{ axid }}.axis line, .axes{{ axid }}.axis path {
        shape-rendering: crispEdges;
        stroke: black;
        fill: none;
    }

    div#figure{{ figid }}
    .axes{{ axid }}.axis text {
        font-family: sans-serif;
        font-size: {{ fontsize }}px;
        fill: black;
        stroke: none;
    }

    div#figure{{ figid }}
    .bg{{ axid }}{
        fill: {{ axesbg }};
    }

    {% for child in children %}
      {{ child.style() }}
    {% endfor %}
    """)

    TEMPLATE = jinja2.Template("""
    // store the width and height of the axes
    var width_{{ axid }} = {{ bbox[2] }} * figwidth;
    var height_{{ axid }} = {{ bbox[3] }} * figheight;

    {% if xscale == 'date' %}
      var xdomain{{ axid }} = [new Date({{ xdaterange[0]|join(", ") }}),
                               new Date({{ xdaterange[1]|join(", ") }})];
    {% else %}
      var xdomain{{ axid }} = [{{ xlim[0] }}, {{ xlim[1] }}];
    {% endif %}

    {% if yscale == 'date' %}
      var ydomain{{ axid }} = [new Date({{ ydaterange[0]|join(", ") }}),
                               new Date({{ ydaterange[1]|join(", ") }})];
    {% else %}
      var ydomain{{ axid }} = [{{ ylim[0] }}, {{ ylim[1] }}];
    {% endif %}

    {% if xscale == 'linear' %}
      var x_{{ axid }} = d3.scale.linear();
      var x_data_map{{ axid }} = x_{{ axid }};
    {% elif xscale == 'log' %}
      var x_{{ axid }} = d3.scale.log();
      var x_data_map{{ axid }} = x_{{ axid }};
    {% elif xscale == 'date' %}
      var x_{{ axid }} = d3.time.scale();
      var x_reverse_{{ axid }} = d3.time.scale()
                                      .domain(xdomain{{ axid }})
                                      .range([{{ xlim[0] }}, {{ xlim[1] }}]);
      var x_data_map{{ axid }} = function(x)
                  { return x_{{ axid }}(x_reverse_{{ axid }}.invert(x));}
    {% endif %}

    {% if yscale == 'linear' %}
      var y_{{ axid }} = d3.scale.linear();
      var y_data_map{{ axid }} = y_{{ axid }};
    {% elif yscale == 'log' %}
      var y_{{ axid }} = d3.scale.log();
      var y_data_map{{ axid }} = y_{{ axid }};
    {% elif yscale == 'date' %}
      var y_{{ axid }} = d3.time.scale();
      var y_reverse_{{ axid }} = d3.time.scale()
                                      .domain(ydomain{{ axid }})
                                      .range([{{ ylim[0] }}, {{ ylim[1] }}]);
      var y_data_map{{ axid }} = function(y)
                  { return y_{{ axid }}(y_reverse_{{ axid }}.invert(y));}
    {% endif %}

    // set axes limits and sizes
    x_{{ axid }}.domain(xdomain{{ axid }})
                .range([0, width_{{ axid }}]);
    y_{{ axid }}.domain(ydomain{{ axid }})
                .range([height_{{ axid }}, 0]);

    // zoom object for the axes
    var zoom{{ axid }} = d3.behavior.zoom()
                    .x(x_{{ axid }})
                    .y(y_{{ axid }})
                    .on("zoom", zoomed{{ axid }});

    // create the axes itself
    var baseaxes_{{ axid }} = canvas.append('g')
            .attr('transform', 'translate(' +
                              ({{ bbox[0] }} * figwidth) + ',' +
                              ((1 - {{ bbox[1] }} - {{ bbox[3] }}) * figheight)
                              + ')')
            .attr('width', width_{{ axid }})
            .attr('height', height_{{ axid }})
            .attr('class', 'main')
            .call(zoom{{ axid }});

    // create the axes background
    baseaxes_{{ axid }}.append("svg:rect")
                      .attr("width", width_{{ axid }})
                      .attr("height", height_{{ axid }})
                      .attr("class", "bg{{ axid }}");

    // axis factory functions: used for grid lines & axes
    var create_xAxis_{{ axid }} = function(){
       return d3.svg.axis()
            .scale(x_{{ axid }})
            .orient('bottom');
    }

    var create_yAxis_{{ axid }} = function(){
       return d3.svg.axis()
            .scale(y_{{ axid }})
            .orient('left');
    }

    // draw the x axis
    var xAxis_{{ axid }} = create_xAxis_{{ axid }}();

    baseaxes_{{ axid }}.append('g')
            .attr('transform', 'translate(0,' + (height_{{ axid }}) + ')')
            .attr('class', 'axes{{ axid }} x axis')
            .call(xAxis_{{ axid }});

    // draw the y axis
    var yAxis_{{ axid }} = create_yAxis_{{ axid }}();

    baseaxes_{{ axid }}.append('g')
            .attr('class', 'axes{{ axid }} y axis')
            .call(yAxis_{{ axid }});

    // create the clip boundary
    var clip_{{ axid }} = baseaxes_{{ axid }}.append("svg:clipPath")
                             .attr("id", "clip{{ axid }}")
                             .append("svg:rect")
                             .attr("x", 0)
                             .attr("y", 0)
                             .attr("width", width_{{ axid }})
                             .attr("height", height_{{ axid }});

    // axes_{axid} is the axes on which to draw plot components: they'll
    // be clipped when zooming or scrolling moves them out of the plot.
    var axes_{{ axid }} = baseaxes_{{ axid }}.append('g')
            .attr("clip-path", "url(#clip{{ axid }})");

    {% for child in children %}
    {{ child.html() }}
    {% endfor %}

    function zoomed{{ axid }}() {
        //console.log(d3.event);  // for some reason this is sometimes null
        //console.log(zoom{{ axid }}.translate());
        //console.log(zoom{{ axid }}.scale());

        baseaxes_{{ axid }}.select(".x.axis").call(xAxis_{{ axid }});
        baseaxes_{{ axid }}.select(".y.axis").call(yAxis_{{ axid }});

        {% for child in children %}
          {{ child.zoom() }}
        {% endfor %}
    }

    function reset{{ axid }}() {
      d3.transition().duration(750).tween("zoom", function() {
        var ix = d3.interpolate(x_{{ axid }}.domain(), xdomain{{ axid }}),
            iy = d3.interpolate(y_{{ axid }}.domain(), ydomain{{ axid }});
        return function(t) {
          zoom{{ axid }}
               .x(x_{{ axid }}.domain(ix(t)))
               .y(y_{{ axid }}.domain(iy(t)));
          zoomed{{ axid }}();
        };
      });
    }

    d3.select("#reset{{ figid }}").on("click", reset{{ axid }});
    """)

    def __init__(self, parent, ax):
        self._initialize(parent=parent, _ax=ax)
        self._axid = self.elid

        self.children = []

        self.children += [D3Image(self, ax, image) for image in ax.images]
        self.children += [D3Grid(self)]
        self.children += [D3Line2D(self, line) for line in ax.lines]
        self.children += [D3Text(self, text) for text in ax.texts]
        self.children += [D3Text(self, text) for text in [ax.xaxis.label,
                                                          ax.yaxis.label,
                                                          ax.title]]
        self.children += [D3Patch(self, patch)
                          for i, patch in enumerate(ax.patches)]

        for collection in ax.collections:
            if isinstance(collection, mpl.collections.PolyCollection):
                self.children.append(D3PatchCollection(self, collection))
            elif isinstance(collection, mpl.collections.LineCollection):
                self.children.append(D3LineCollection(self, collection))
            elif isinstance(collection, mpl.collections.QuadMesh):
                self.children.append(D3QuadMesh(self, collection))
            elif isinstance(collection, mpl.collections.PathCollection):
                self.children.append(D3PathCollection(self, collection))
            else:
                warnings.warn("{0} not implemented.  "
                              "Elements will be ignored".format(collection))

        # Some warnings for pieces of matplotlib which are not yet implemented
        for attr in ['artists', 'tables']:
            if len(getattr(ax, attr)) > 0:
                warnings.warn("{0} not implemented.  "
                              "Elements will be ignored".format(attr))

        if ax.legend_ is not None:
            warnings.warn("legend is not implemented: it will be ignored")

    def style(self):
        axesbg = color_to_hex(self.ax.patch.get_facecolor())
        ticks = self.ax.xaxis.get_ticklabels() + self.ax.yaxis.get_ticklabels()

        if len(ticks) == 0:
            fontsize_x = 11
        else:
            fontsize_x = ticks[0].properties()['size']

        return self.STYLE.render(axid=self.axid,
                                 figid=self.figid,
                                 axesbg=axesbg,
                                 fontsize=fontsize_x,
                                 children=self.children)

    def _get_axis_args(self):
        args = {}
        for axname in ['x', 'y']:
            axis = getattr(self.ax, axname + 'axis')
            if isinstance(axis.converter, mpl.dates.DateConverter):
                dtup = lambda d: (d.year, d.month - 1, d.day, d.hour,
                                  d.minute, d.second, d.microsecond / 1e3)
                daterange = map(dtup, mpl.dates.num2date(self.ax.get_xlim()))
                scale = 'date'
            else:
                scale = axis.get_scale()
                daterange = None

            if scale not in ['date', 'linear', 'log']:
                raise ValueError("Unknown axis scale: "
                                 "{0}".format(axis[xy].get_scale()))

            args[axname + 'daterange'] = daterange
            args[axname + 'scale'] = scale
        return args

    def html(self):
        return self.TEMPLATE.render(figid=self.figid,
                                    axid=self.axid,
                                    bbox=self.ax.get_position().bounds,
                                    children=self.children,
                                    xlim=self.ax.get_xlim(),
                                    ylim=self.ax.get_ylim(),
                                    **self._get_axis_args())


class D3Grid(D3Base):
    """Class for representing a matplotlib Axes grid in D3js"""
    STYLE = """
    div#figure{figid}
    .grid .tick {{
      stroke: {color};
      stroke-dasharray: {dasharray};
      stroke-opacity: {alpha};
    }}

    div#figure{figid}
    .grid path {{
      stroke-width: 0;
    }}
    """

    TEMPLATE = jinja2.Template("""
    {% if gridx %}
    // draw x grid lines: we use a second x-axis with long ticks
    axes_{{ axid }}.append("g")
         .attr("class", "axes{{ axid }} x grid")
         .attr("transform", "translate(0," + (height_{{ axid }}) + ")")
         .call(create_xAxis_{{ axid }}()
                       .tickSize(-(height_{{ axid }}), 0, 0)
                       .tickFormat(""));
    {% endif %}

    {% if gridy %}
    // draw y grid lines: we use a second y-axis with long ticks
    axes_{{ axid }}.append("g")
         .attr("class", "axes{{ axid }} y grid")
         .call(create_yAxis_{{ axid }}()
                       .tickSize(-(width_{{ axid }}), 0, 0)
                       .tickFormat(""));
    {% endif %}
    """)

    ZOOM = jinja2.Template("""
    {% if gridx %}
        axes_{{ axid }}.select(".x.grid")
            .call(create_xAxis_{{ axid }}()
            .tickSize(-height_{{ axid }}, 0, 0)
            .tickFormat(""));
    {% endif %}

    {% if gridy %}
        axes_{{ axid }}.select(".y.grid")
            .call(create_yAxis_{{ axid }}()
            .tickSize(-width_{{ axid }}, 0, 0)
            .tickFormat(""));
    {% endif %}
    """)

    def __init__(self, parent):
        self._initialize(parent=parent)

    def zoom(self):
        return self.ZOOM.render(axid=self.axid,
                                gridx=self.ax.xaxis._gridOnMajor,
                                gridy=self.ax.yaxis._gridOnMajor)

    def html(self):
        return self.TEMPLATE.render(axid=self.axid,
                                    gridx=self.ax.xaxis._gridOnMajor,
                                    gridy=self.ax.yaxis._gridOnMajor)

    def style(self):
        gridlines = (self.ax.xaxis.get_gridlines() +
                     self.ax.yaxis.get_gridlines())
        color = color_to_hex(gridlines[0].get_color())
        alpha = gridlines[0].get_alpha()
        dasharray = get_dasharray(gridlines[0])
        return self.STYLE.format(color=color,
                                 alpha=alpha,
                                 figid=self.figid,
                                 dasharray=dasharray)


class D3Line2D(D3Base):
    """Class for representing a 2D matplotlib line in D3js"""
    DATA_TEMPLATE = """
    var data_{lineid} = {data}
    """

    STYLE = """
    div#figure{figid}
    path.line{lineid} {{
        stroke: {linecolor};
        stroke-width: {linewidth};
        stroke-dasharray: {dasharray};
        fill: none;
        stroke-opacity: {alpha};
    }}

    div#figure{figid}
    path.points{lineid} {{
        stroke-width: {markeredgewidth};
        stroke: {markeredgecolor};
        fill: {markercolor};
        fill-opacity: {alpha};
        stroke-opacity: {alpha};
    }}
    """

    LINE_ZOOM = """
        axes_{axid}.select(".line{lineid}")
                       .attr("d", line_{lineid}(data_{lineid}));
    """

    POINTS_ZOOM = """
        axes_{axid}.selectAll(".points{lineid}")
              .attr("transform", function(d)
                {{ return "translate(" + x_data_map{axid}(d[0]) + "," +
                   y_data_map{axid}(d[1]) + ")"; }});
    """

    LINE_TEMPLATE = """
    var line_{lineid} = d3.svg.line()
         .x(function(d) {{return x_data_map{axid}(d[0]);}})
         .y(function(d) {{return y_data_map{axid}(d[1]);}})
         .defined(function (d) {{return !isNaN(d[0]) && !isNaN(d[1]); }})
         .interpolate("linear");

    axes_{axid}.append("svg:path")
                   .attr("d", line_{lineid}(data_{lineid}))
                   .attr('class', 'line{lineid}');
    """

    POINTS_TEMPLATE = """
    var g_{lineid} = axes_{axid}.append("svg:g");

    g_{lineid}.selectAll("scatter-dots-{lineid}")
          .data(data_{lineid}.filter(
            function(d) {{return !isNaN(d[0]) && !isNaN(d[1]); }}))
          .enter().append("svg:path")
              .attr('class', 'points{lineid}')
              .attr("d", d3.svg.symbol()
                            .type("{markershape}")
                            .size({markersize}))
              .attr("transform", function(d)
                  {{ return "translate(" + x_data_map{axid}(d[0]) +
                     "," + y_data_map{axid}(d[1]) + ")"; }});
    """

    def __init__(self, parent, line):
        self._initialize(parent=parent, line=line)
        self.lineid = self.elid

    def zoomable(self):
        return self.line.get_transform().contains_branch(self.ax.transData)

    def has_line(self):
        return self.line.get_linestyle() not in ['', ' ', 'None', 'none', None]

    def has_points(self):
        return self.line.get_marker() not in ['', ' ', 'None', 'none', None]

    def zoom(self):
        ret = ""
        if self.zoomable():
            if self.has_points():
                ret += self.POINTS_ZOOM.format(lineid=self.lineid,
                                               axid=self.axid)
            if self.has_line():
                ret += self.LINE_ZOOM.format(lineid=self.lineid,
                                             axid=self.axid)
        return ret

    def style(self):
        alpha = self.line.get_alpha()
        if alpha is None:
            alpha = 1
        lc = color_to_hex(self.line.get_color())
        lw = self.line.get_linewidth()
        mc = color_to_hex(self.line.get_markerfacecolor())
        mec = color_to_hex(self.line.get_markeredgecolor())
        mew = self.line.get_markeredgewidth()
        dasharray = get_dasharray(self.line)

        return self.STYLE.format(figid=self.figid,
                                 lineid=self.lineid,
                                 linecolor=lc,
                                 linewidth=lw,
                                 markeredgewidth=mew,
                                 markeredgecolor=mec,
                                 markercolor=mc,
                                 dasharray=dasharray,
                                 alpha=alpha)

    def html(self):
        transform = self.line.get_transform() - self.ax.transData
        data = transform.transform(self.line.get_xydata()).tolist()

        result = self.DATA_TEMPLATE.format(lineid=self.lineid,
                                           data=json.dumps(data))

        if self.has_line():
            result += self.LINE_TEMPLATE.format(lineid=self.lineid,
                                                axid=self.axid)
        if self.has_points():
            marker = self.line.get_marker()
            msh = get_d3_shape_for_marker(marker)
            ms = self.line.get_markersize() ** 2
            result += self.POINTS_TEMPLATE.format(lineid=self.lineid,
                                                  axid=self.axid,
                                                  markersize=ms,
                                                  markershape=msh)
        return result


class D3LineCollection(D3Base):
    """Class to represent LineCollections in D3"""
    def __init__(self, parent, collection):
        self._initialize(parent=parent, collection=collection)
        self.lines = []

        collection.update_scalarmappable()
        colors = collection.get_colors()
        linewidths = collection.get_linewidths()
        styles = collection.get_linestyles()
        for i, path in enumerate(collection.get_paths()):
            line_segment = Line2D(path.vertices[:, 0], path.vertices[:, 1],
                                  linewidth=linewidths[i % len(linewidths)],
                                  color=colors[i % len(colors)],
                                  transform=collection.get_transform())
            style = styles[i % len(styles)][1]
            if style is not None:
                line_segment.set_dashes(style)
            self.lines.append(D3Line2D(parent, line_segment))

    def zoom(self):
        return "\n".join([line.zoom() for line in self.lines])

    def style(self):
        return "\n".join([line.style() for line in self.lines])

    def html(self):
        return "\n".join([line.html() for line in self.lines])


class D3Text(D3Base):
    """Class for representing matplotlib text in D3js"""
    FIG_TEXT_TEMPLATE = """
    canvas.append("text")
        .text("{text}")
        .attr("class", "text{textid}")
        .attr("x", {x})
        .attr("y", figheight - {y})
        .attr("font-size", "{fontsize}px")
        .attr("fill", "{color}")
        .attr("transform", "rotate({rotation},{x}," + (figheight - {y}) + ")")
        .attr("style", "text-anchor: {h_anchor};")
    """

    AXES_TEXT_TEMPLATE = """
    axes_{axid}.append("text")
        .text("{text}")
        .attr("class", "text{textid}")
        .attr("x", x_data_map{axid}({x}))
        .attr("y", y_data_map{axid}({y}))
        .attr("font-size", "{fontsize}px")
        .attr("fill", "{color}")
        .attr("transform", "rotate({rotation},{x}," + (figheight - {y}) + ")")
        .attr("style", "text-anchor: {h_anchor};")
    """

    AXES_TEXT_ZOOM = """
        axes_{axid}.select(".text{textid}")
                       .attr("x", x_data_map{axid}({x}))
                       .attr("y", y_data_map{axid}({y}))
    """

    def __init__(self, parent, text):
        self._initialize(parent=parent, text=text)
        self.textid = self.elid

    def zoomable(self):
        return self.text.get_transform().contains_branch(self.ax.transData)

    def zoom(self):
        if self.zoomable():
            x, y = self.text.get_position()
            return self.AXES_TEXT_ZOOM.format(x=x, y=y, axid=self.axid,
                                              textid=self.textid)
        else:
            return ''

    def html(self):
        text_content = self.text.get_text()
        x, y = self.text.get_position()

        if not text_content:
            return ''

        if self.zoomable():
            template = self.AXES_TEXT_TEMPLATE

        else:
            # convert (x, y) to figure coordinates
            x, y = self.text.get_transform().transform((x, y))
            template = self.FIG_TEXT_TEMPLATE

        color = color_to_hex(self.text.get_color())
        fontsize = self.text.get_size()
        rotation = -self.text.get_rotation()

        # TODO: fix vertical anchor point
        h_anchor = {'left': 'start',
                    'center': 'middle',
                    'right': 'end'}[self.text.get_horizontalalignment()]

        # hack for y-label alignment
        if self.text is self.ax.yaxis.label:
            x += fontsize

        return template.format(x=x, y=y, axid=self.axid,
                               textid=self.textid,
                               text=text_content,
                               fontsize=fontsize,
                               color=color,
                               rotation=rotation,
                               h_anchor=h_anchor)


class D3Patch(D3Base):
    """Class for representing matplotlib patches in D3js"""
    STYLE = """
    div#figure{figid}
    path.patch{elid} {{
        stroke: {linecolor};
        stroke-width: {linewidth};
        stroke-dasharray: {dasharray};
        fill: {fillcolor};
        stroke-opacity: {alpha};
        fill-opacity: {alpha};
    }}
    """

    TEMPLATE = """
    var data_{elid} = {data};

    {construct_SVG_path}

    axes_{axid}.append("svg:path")
                   .attr("d", construct_SVG_path(data_{elid},
                                                 x_data_map{axid},
                                                 y_data_map{axid}))
                   .attr("vector-effect", "non-scaling-stroke")
                   .attr('class', 'patch{elid}');
    """

    ZOOM = """
        axes_{axid}.select(".patch{elid}")
              .attr("d", construct_SVG_path(data_{elid},
                                            x_data_map{axid},
                                            y_data_map{axid}))
    """

    def __init__(self, parent, patch):
        self._initialize(parent=parent, patch=patch)
        self.patchid = self.elid

    def zoomable(self):
        return self.patch.get_transform().contains_branch(self.ax.transData)

    def zoom(self):
        if self.zoomable():
            return self.ZOOM.format(axid=self.axid,
                                    elid=self.elid)
        else:
            return ""

    def style(self):
        ec = self.patch.get_edgecolor()
        if self.patch.get_fill():
            fc = color_to_hex(self.patch.get_facecolor())
        else:
            fc = "none"

        alpha = self.patch.get_alpha()
        if alpha is None:
            alpha = 1
        lc = color_to_hex(self.patch.get_edgecolor())
        lw = self.patch.get_linewidth()
        dasharray = get_dasharray(self.patch)

        return self.STYLE.format(figid=self.figid,
                                 elid=self.elid,
                                 linecolor=lc,
                                 linewidth=lw,
                                 fillcolor=fc,
                                 dasharray=dasharray,
                                 alpha=alpha)

    def data(self):
        # transform path to data coordinates
        transform = self.patch.get_transform() - self.ax.transData
        return path_data(self.patch.get_path(), transform)

    def html(self):
        return self.TEMPLATE.format(axid=self.axid, elid=self.elid,
                                    construct_SVG_path=CONSTRUCT_SVG_PATH,
                                    data=json.dumps(self.data()))


class D3Collection(D3Base):
    """Class for representing matplotlib path collections in D3js"""

    # TODO: when all paths have same offset, or all offsets have same paths,
    #       this can be done more efficiently.

    PATH_FUNC_NOZOOM = """
    var path_func_{elid} = function(d){{
         var path = d.p ? d.p : {defaults.p};
         var size = d.s ? d.s : {defaults.s};
         return construct_SVG_path(path,
                                   function(x){{return size * x;}},
                                   function(y){{return size * y;}});
    }}
    """

    PATH_FUNC_ZOOM = """
    var path_func_{elid} = function(d){{
         var path = d.p ? d.p : {defaults.p};
         var size = d.s ? d.s : {defaults.s};
         return construct_SVG_path(path,
                         function(x){{return x_data_map{axid}(size * x);}},
                         function(y){{return y_data_map{axid}(size * y);}});
    }}
    """

    OFFSET_FUNC_NOZOOM = """
    var offset_func_{elid} = function(d){{
         var offset = d.o ? d.o : {defaults.o};
         return "translate(" + offset + ")";
    }}
    """

    OFFSET_FUNC_ZOOM = """
    var offset_func_{elid} = function(d){{
         var offset = d.o ? d.o : {defaults.o};
         return "translate(" + x_data_map{axid}(offset[0]) +
                           "," + y_data_map{axid}(offset[1]) + ")";
    }}
    """

    TEMPLATE = """
    var data_{elid} = {data}

    {construct_SVG_path}

    var g_{elid} = axes_{axid}.append("svg:g");

    var style_func_{elid} = function(d){{
       var edgecolor = d.ec ? d.ec : {defaults.ec};
       var facecolor = d.fc ? d.fc : {defaults.fc};
       var linewidth = d.lw ? d.lw : {defaults.lw};
       var dasharray = d.ls ? d.ls : {defaults.ls};
       return "stroke: " + edgecolor + "; " +
              "stroke-width: " + linewidth + "; " +
              "stroke-dasharray: " + dasharray + "; " +
              "fill: " + facecolor + "; " +
              "stroke-opacity: {defaults.alpha}; " +
              "fill-opacity: {defaults.alpha}";
    }}

    g_{elid}.selectAll("paths-{elid}")
          .data(data_{elid})
          .enter().append("svg:path")
              .attr('class', 'paths{elid}')
              .attr("d", path_func_{elid})
              .attr("style", style_func_{elid})
              .attr("transform", offset_func_{elid});
    """

    ZOOM_BASE = """
        axes_{axid}.selectAll(".paths{elid}")"""

    ZOOM_PATH = """
              .attr("d", path_func_{elid})"""

    ZOOM_OFFSET = """
              .attr("transform", offset_func_{elid})"""

    def __init__(self, parent, collection):
        self._initialize(parent, collection=collection)

    def _update_data(self, data, defaults):
        return data, defaults

    def offset_zoomable(self):
        transform = self.collection.get_offset_transform()
        return transform.contains_branch(self.ax.transData)

    def path_zoomable(self):
        transform = self.collection.get_transform()
        return transform.contains_branch(self.ax.transData)

    def html(self):
        template = self.TEMPLATE

        if self.collection.get_transforms() != []:
            warnings.warn("Collection: multiple transforms not implemented. "
                          "They will be ignored.")

        if self.offset_zoomable():
            offset_transform = (self.collection.get_offset_transform()
                                - self.ax.transData)
            template = self.OFFSET_FUNC_ZOOM + template
        else:
            offset_transform = self.collection.get_offset_transform()
            template = self.OFFSET_FUNC_NOZOOM + template

        if self.path_zoomable():
            path_transform = (self.collection.get_transform()
                              - self.ax.transData)
            template = self.PATH_FUNC_ZOOM + template
        else:
            path_transform = self.collection.get_transform()
            template = self.PATH_FUNC_NOZOOM + template

        offsets = [offset_transform.transform(offset).tolist()
                   for offset in self.collection.get_offsets()]
        paths = [path_data(path, path_transform)
                 for path in self.collection.get_paths()]

        data = {'o': offsets,
                'p': paths}
        defaults = {}

        self.collection.update_scalarmappable()  # this updates colors
        data['ec'] = map(color_to_hex, self.collection.get_edgecolors())
        defaults['ec'] = 'none'

        data['fc'] = map(color_to_hex, self.collection.get_facecolors())
        defaults['fc'] = 'none'

        data['alpha'] = self.collection.get_alpha()
        defaults['alpha'] = 1

        data['lw'] = self.collection.get_linewidths()
        defaults['lw'] = 1

        data['ls'] = [get_dasharray(self.collection, i)
                      for i in range(len(self.collection.get_linestyles()))]
        defaults['ls'] = "10,0"

        # make the size scaling default equal to 1
        data['s'] = 1

        # process the data and defaults
        data, defaults = self._update_data(data, defaults)
        data, defaults = collection_data(data, defaults)

        return template.format(elid=self.elid, axid=self.axid,
                               construct_SVG_path=CONSTRUCT_SVG_PATH,
                               data=json.dumps(data),
                               defaults=defaults)

    def zoom(self):
        zoom = self.ZOOM_BASE
        if self.path_zoomable():
            zoom += self.ZOOM_PATH
        if self.offset_zoomable():
            zoom += self.ZOOM_OFFSET
        return zoom.format(elid=self.elid, axid=self.axid)

    def style(self):
        return ""


class D3PathCollection(D3Collection):
    def _update_data(self, data, defaults):
        defaults['s'] = 1
        sizes = self.collection.get_sizes()
        if sizes is not None:
            sizes = np.sqrt(sizes) * self.fig.dpi / 72.
        data['s'] = sizes
        return data, defaults


class D3QuadMesh(D3Collection):
    def __init__(self, *args, **kwargs):
        warnings.warn("Not all QuadMesh features are yet implemented")
        D3Collection.__init__(self, *args, **kwargs)


class _D3LineCollection(D3Collection):
    def _update_data(self, data, defaults):
        # Hack to make length of paths match length of colors.
        # not sure why there is one more color than the number of paths.
        data['p'].append([['M', [0, 0]]])

        return data, defaults


class D3PatchCollection(D3Base):
    """Class for representing matplotlib patch collections in D3js"""
    STYLE = """
    div#figure{figid}
    path.coll{elid}.patch{i} {{
        stroke: {linecolor};
        stroke-width: {linewidth};
        stroke-dasharray: {dasharray};
        fill: {fillcolor};
        stroke-opacity: {alpha};
        fill-opacity: {alpha};
    }}
    """

    TEMPLATE = """
    var data_{pathid} = {data}

    var patch_{pathid} = d3.svg.line()
         .x(function(d) {{return x_data_map{axid}(d[0]);}})
         .y(function(d) {{return y_data_map{axid}(d[1]);}})
         .interpolate("{interpolate}");

    axes_{axid}.append("svg:path")
                   .attr("d", patch_{pathid}(data_{pathid}))
                   .attr('class', 'coll{elid} patch{i}');
    """

    ZOOM = """
        axes_{axid}.select(".coll{elid}.patch{i}")
                       .attr("d", patch_{pathid}(data_{pathid}));
    """

    # TODO: there are special D3 classes for many common patch types
    #       (i.e. circle, ellipse, rectangle, polygon, etc.)  We should
    #       use these where possible.  Also, it would be better to use the
    #       SVG path codes as in D3Patch(), above.

    def __init__(self, parent, collection):
        self._initialize(parent=parent, collection=collection)
        self.n_paths = len(collection.get_paths())

    def pathid(self, i):
        return self.elid + str(i + 1)

    def zoom(self):
        return "".join([self.ZOOM.format(axid=self.axid,
                                         i=i + 1,
                                         pathid=self.pathid(i),
                                         elid=self.elid)
                        for i in range(self.n_paths)])

    def style(self):
        alpha = self.collection.get_alpha()
        if alpha is None:
            alpha = 1

        ec = self.collection.get_edgecolor()
        fc = self.collection.get_facecolor()
        lc = self.collection.get_edgecolor()
        lw = self.collection.get_linewidth()

        styles = []
        for i in range(self.n_paths):
            dasharray = get_dasharray(self.collection, i)
            styles.append(self.STYLE.format(figid=self.figid,
                                            elid=self.elid,
                                            i=i + 1,
                                            linecolor=color_to_hex(lc[i]),
                                            linewidth=lw[i],
                                            fillcolor=color_to_hex(fc[i]),
                                            dasharray=dasharray,
                                            alpha=alpha))
        return '\n'.join(styles)

    def html(self):
        results = []
        for i, path in enumerate(self.collection.get_paths()):
            data = path.vertices.tolist()
            results.append(self.TEMPLATE.format(axid=self.axid,
                                                elid=self.elid,
                                                pathid=self.pathid(i),
                                                i=i + 1,
                                                data=json.dumps(data),
                                                interpolate="linear"))
        return '\n'.join(results)


class D3Image(D3Base):
    """Class for representing matplotlib images in D3js"""
    IMAGE_TEMPLATE = """
    axes_{axid}.append("svg:image")
        .attr('class', 'image{imageid}')
        .attr("x", x_{axid}({x}))
        .attr("y", y_{axid}({y}))
        .attr("width", x_{axid}({width}) - x_{axid}({x}))
        .attr("height", y_{axid}({height}) - y_{axid}({y}))
        .attr("xlink:href", "data:image/png;base64," + "{base64_data}")
        .attr("preserveAspectRatio", "none");
    """

    IMAGE_ZOOM = """
        axes_{axid}.select(".image{imageid}")
                   .attr("x", x_{axid}({x}))
                   .attr("y", y_{axid}({y}))
                   .attr("width", x_{axid}({width}) - x_{axid}({x}))
                   .attr("height", y_{axid}({height}) - y_{axid}({y}));
    """

    def __init__(self, parent, ax, image, i=''):
        self._initialize(parent=parent, ax=ax, image=image)
        self.imageid = "{0}{1}".format(self.axid, i)

    def zoom(self):
        return self.IMAGE_ZOOM.format(imageid=self.imageid,
                                      axid=self.axid,
                                      x=self.x, y=self.y,
                                      width=self.width, height=self.height)

    def html(self):
        self.x, self.y = 0, 0
        data = self.image.get_array().data
        self.height, self.width = data.shape

        binary_buffer = io.BytesIO()
        imsave(binary_buffer, data)
        binary_buffer.seek(0)
        base64_data = base64.b64encode(binary_buffer.read())

        return self.IMAGE_TEMPLATE.format(axid=self.axid,
                                          imageid=self.imageid,
                                          base64_data=base64_data,
                                          x=self.x, y=self.y,
                                          width=self.width, height=self.height)

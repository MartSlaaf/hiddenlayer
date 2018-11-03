"""
graph.py

Graph class.
Tracks nodes and edges of a directed graph and supports basic operations on them.

Written by Waleed Abdulla, additions by Phil Ferriere

Licensed under the MIT License

Refs:
    graphviz Graph API
    @ http://graphviz.readthedocs.io/en/stable/api.html#graph
"""
from __future__ import absolute_import, division, print_function
import os
import re
from random import getrandbits
import numpy as np
from graphviz import Digraph


THEMES = {
    "basic": {
        "background_color": "#FFFFFF",
        "fill_color": "#E8E8E8",
        "outline_color": "#000000",
        "font_color": "#000000",
        "font_name": "Times",
        "font_size": "10",
        "margin": "0,0",
        "padding":  "1.0,0.5",
    },
    "blue": {
        "background_color": "#FFFFFF",
        "fill_color": "#BCD6FC",
        "outline_color": "#7C96BC",
        "font_color": "#202020",
        "font_name": "Verdana",
        "font_size": "10",
        "margin": "0,0",
        "padding":  "1.0,0.5",
    },
}


###########################################################################
# Utility Functions
###########################################################################

def detect_framework(value):
    classes = (value.__class__,) + value.__class__.__bases__
    for c in classes:
        if c.__module__.startswith("torch"):
            return "torch"
        elif c.__module__.startswith("tensorflow"):
            return "tensorflow"


###########################################################################
# Node
###########################################################################

class Node():
    """Represents a framework-agnostic neural network layer in a directed graph."""

    def __init__(self, uid, name, op, output_shape=None, params=None):
        """
        uid: unique ID for the layer that doesn't repeat in the computation graph.
        name: Name to display
        op: Framework-agnostic operation name.
        """
        self.id = uid
        self.name = name  # TODO: clarify op vs name vs title
        self.op = op
        self.repeat = 1
        if output_shape:
            assert isinstance(output_shape, (tuple, list)),\
            "output_shape must be a tuple or list but received {}".format(type(output_shape))
        self.output_shape = output_shape
        self.params = params if params else {}
        self._caption = ""

    @property
    def title(self):
        # Default
        title = self.name or self.op

        if "kernel_shape" in self.params:
            # Kernel
            kernel = self.params["kernel_shape"]
            title += "x".join(map(str, kernel))
        #         # Transposed
        #         if node.transposed:
        #             name = "Transposed" + name
        return title

    @property
    def caption(self):
        if self._caption:
            return self._caption

        caption = ""

        # Stride
        if "stride" in self.params:
            stride = self.params["stride"]
            if np.unique(stride).size == 1:
                stride = stride[0]
            if stride != 1:
                caption += "/{}".format(str(stride))
        return caption

    def __repr__(self):
        args = (self.op, self.name, self.id, self.title, self.repeat)
        f = "<Node: op: {}, name: {}, id: {}, title: {}, repeat: {}"
        if self.output_shape:
            args += (str(self.output_shape),)
            f += ", shape: {:}"
        if self.params:
            args += (str(self.params),)
            f += ", params: {:}"
        f += ">"
        return f.format(*args)

    # TODO
    # def __eq__(self, a):
    #     assert isinstance(a, Layer)
    #     if self.params and a.params:
    #         return hash(self.params) == hash(a.params)
    #     elif not self.params and not a.params:
    #         return True
    #     else:
    #         return False


###########################################################################
# Graph
###########################################################################

class Graph():
    """Tracks nodes and edges of a directed graph and supports basic operations on them."""

    def __init__(self, model=None, args=None, input_names=None,
                 transforms="default", framework_transforms="default",
                 meaningful_ids=False):
        self.nodes = {}
        self.edges = []
        self.meaningful_ids = meaningful_ids # TODO
        self.theme = THEMES["basic"]

        if model:
            # Detect framwork
            framework = detect_framework(model)
            if framework == "torch":
                from .pytorch_builder import import_graph, FRAMEWORK_TRANSFORMS
                assert args is not None, "Argument args must be provided for Pytorch models."
                import_graph(self, model, args)
            elif framework == "tensorflow":
                from .tf_builder import import_graph, FRAMEWORK_TRANSFORMS
                import_graph(self, model)
            
            # Apply Transforms
            if framework_transforms:
                if framework_transforms == "default":
                    framework_transforms = FRAMEWORK_TRANSFORMS
                for t in framework_transforms:
                    t.apply(self)
            if transforms:
                if transforms == "default":
                    from .transforms import SIMPLICITY_TRANSFORMS  # TODO: doesn't belong here
                    transforms = SIMPLICITY_TRANSFORMS
                for t in transforms:
                    t.apply(self)


    def id(self, node):
        """Returns a unique node identifier. If the node has an id
        attribute (preferred), it's used. Otherwise, the hash() is returned."""
        return node.id if hasattr(node, "id") else hash(node)

    def add_node(self, node):
        id = self.id(node)
        # assert(id not in self.nodes)
        self.nodes[id] = node

    def add_edge(self, node1, node2, label=None):
        # If the edge is already present, don't add it again.
        # TODO: If an edge exists with a different label, still don't add it again.
        edge = (self.id(node1), self.id(node2), label)
        if edge not in self.edges:
            self.edges.append(edge)

    def add_edge_by_id(self, vid1, vid2, label=None):
        self.edges.append((vid1, vid2, label))

    def outgoing(self, node):
        """Returns IDs of nodes connecting out of the given node."""
        # TODO: update to return nodes rather than IDs
        node = node if isinstance(node, list) else [node]
        node_ids = [self.id(n) for n in node]
        outgoing = [e[1] for e in self.edges if e[0] in node_ids]
        return list(set(outgoing))

    def incoming(self, node):
        """Returns IDs of nodes connecting to the given node."""
        # TODO: update to return nodes rather than IDs
        return [e[0] for e in self.edges if e[1] == self.id(node)]

    def siblings(self, node):
        """Returns all nodes that share the same parent (incoming node) with
        the given node, including the node itself.
        """
        incoming = self.incoming(node)
        # TODO: Not handling the case of multiple incoming nodes yet
        if len(incoming) == 1:
            incoming = self[incoming[0]]
            siblings = self[self.outgoing(incoming)]
            return siblings
        else:
            return [node]

    def __getitem__(self, key):
        if isinstance(key, list):
            return [self.nodes.get(k) for k in key]
        else:
            return self.nodes.get(key)

    def remove(self, nodes):
        """Remove a node and its edges."""
        nodes = nodes if isinstance(nodes, list) else [nodes]
        for node in nodes:
            k = self.id(node)
            self.edges = list(filter(lambda e: e[0] != k and e[1] != k, self.edges))
            del self.nodes[k]

    def replace(self, nodes, node):
        """Replace nodes with node. Edges incoming to nodes[0] are connected to
        the new node, and nodes outgoing from nodes[-1] become outgoing from
        the new node."""
        nodes = nodes if isinstance(nodes, list) else [nodes]
        # Is the new node part of the replace nodes (i.e. want to collapse
        # a group of nodes into one of them)?
        collapse = self.id(node) in self.nodes
        # Add new node and edges
        if not collapse:
            self.add_node(node)
        for k in self.incoming(nodes[0]):
            in_node = self.nodes[k]
            # TODO: it's not clean to have to check if node has output_shape
            self.add_edge(in_node, node, in_node.output_shape if hasattr(in_node, "output_shape") else None)
        for k in self.outgoing(nodes[-1]):
            self.add_edge(node, self[k], node.output_shape if hasattr(node, "output_shape") else None)
        # Remove the old nodes
        for n in nodes:
            if collapse and n == node:
                continue
            self.remove(n)

    def search(self, pattern):
        """Searches the graph for a sub-graph that matches the given pattern
        and returns the first match it finds.
        """
        for node in self.nodes.values():
            match, following = pattern.match(self, node)
            if match:
                return match, following
        return [], None


    def sequence_id(self, sequence):
        """Make up an ID for a sequence (list) of nodes.
        Note: `getrandbits()` is very uninformative as a "readable" ID. Here, we build a name
        such that when the mouse hovers over the drawn node in Jupyter, one can figure out
        which original nodes make up the sequence. This is actually quite useful.
        """
        if self.meaningful_ids:
            # TODO: does this work for PyTorch?
            return "><".join([node.id for node in sequence])
        else:
            return getrandbits(64)

    def build_dot(self):
        """Generate a GraphViz Dot graph.

        Returns a GraphViz Digraph object.
        """
        # Build GraphViz Digraph
        dot = Digraph()
        dot.attr("graph", 
                 bgcolor=self.theme["background_color"],
                 color=self.theme["outline_color"],
                 fontsize=self.theme["font_size"],
                 fontcolor=self.theme["font_color"],
                 fontname=self.theme["font_name"],
                 margin=self.theme["margin"],
                 pad=self.theme["padding"])
        dot.attr("node", shape="box", 
                 style="filled", margin="0,0",
                 fillcolor=self.theme["fill_color"],
                 color=self.theme["outline_color"],
                 fontsize=self.theme["font_size"],
                 fontcolor=self.theme["font_color"],
                 fontname=self.theme["font_name"])
        dot.attr("edge", style="doted", 
                 color=self.theme["outline_color"],
                 fontsize=self.theme["font_size"],
                 fontcolor=self.theme["font_color"],
                 fontname=self.theme["font_name"])

        for k, n in self.nodes.items():
            label = "<tr><td cellpadding='6'>{}</td></tr>".format(n.title)
            if n.caption:
                label += "<tr><td>{}</td></tr>".format(n.caption)
            if n.repeat > 1:
                label += "<tr><td align='right' cellpadding='2'>x{}</td></tr>".format(n.repeat)
            label = "<<table border='0' cellborder='0' cellpadding='0'>" + label + "</table>>"

            if True or n.repeat == 1:  # TODO:
                dot.node(str(k), label)
            # else:
            #     with dot.subgraph(name="cluster {}".format(n.id)) as s:
            #         s.attr(label="x{}".format(n.repeat),
            #                labelloc="br", labeljust="r",
            #                style="dashed")
            #         s.node(str(k), label)
        for a, b, label in self.edges:
            if isinstance(label, list):
                label = "x".join(map(str, label))

            dot.edge(str(a), str(b), label)
        return dot

    # TODO: needed?
    def list_layers(self):
        """List the layers in the graph (for debugging purposes).
        """
        for layer in self.nodes.values():
            print(layer)

    def _repr_svg_(self):
        """Allows Jupyter notebook to render the graph automatically."""
        return self.build_dot()._repr_svg_()
    
    def save(self, path, format="pdf"):
        # TODO: assert on format
        dot = self.build_dot()
        dot.format = format
        directory, file_name = os.path.split(path)
        # Remove extension from file name. dot.render() adds it.
        file_name = file_name.replace("." + format, "")
        dot.render(file_name, directory=directory, cleanup=True)
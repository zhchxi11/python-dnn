# Copyright 2013    Yajie Miao    Carnegie Mellon University

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#  http://www.apache.org/licenses/LICENSE-2.0
#
# THIS CODE IS PROVIDED *AS IS* BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, EITHER EXPRESS OR IMPLIED, INCLUDING WITHOUT LIMITATION ANY IMPLIED
# WARRANTIES OR CONDITIONS OF TITLE, FITNESS FOR A PARTICULAR PURPOSE,
# MERCHANTABLITY OR NON-INFRINGEMENT.
# See the Apache 2 License for the specific language governing permissions and
# limitations under the License.

import cPickle
import gzip
import os
import sys
import time

import numpy
from collections import OrderedDict

import theano
import theano.tensor as T
from theano.tensor.shared_randomstreams import RandomStreams

from layers.logistic_sgd import LogisticRegression
from layers.mlp import HiddenLayer, DropoutHiddenLayer, _dropout_from_layer

from models import nnet


class DNN_Dropout(nnet):

    def __init__(self, numpy_rng, theano_rng=None, n_ins=784,
                 hidden_layers_sizes=[500, 500], n_outs=10,
                 activation = T.nnet.sigmoid,
                 input_dropout_factor = 0,
                 dropout_factor = [0.2,0.2,0.2,0.2,0.2,0.2,0.2],
                 do_maxout = False, pool_size = 1,
                 max_col_norm = None, l1_reg = None, l2_reg = None):

        super(DNN_Dropout, self).__init__()

        self.mlp_layers = []
        self.dropout_layers = []
        self.n_layers = len(hidden_layers_sizes)

        self.max_col_norm = max_col_norm
        self.l1_reg = l1_reg
        self.l2_reg = l2_reg

        self.input_dropout_factor = input_dropout_factor
        self.dropout_factor = dropout_factor

        assert self.n_layers > 0

        if not theano_rng:
            theano_rng = RandomStreams(numpy_rng.randint(2 ** 30))
        # allocate symbolic variables for the data
        self.x = T.matrix('x') 
        self.y = T.ivector('y')

        for i in xrange(self.n_layers):
            # construct the sigmoidal layer
            if i == 0:
                input_size = n_ins
                layer_input = self.x
                if input_dropout_factor > 0.0:
                    dropout_layer_input = _dropout_from_layer(theano_rng, self.x, input_dropout_factor)
                else:
                    dropout_layer_input = self.x
            else:
                input_size = hidden_layers_sizes[i - 1]
                layer_input = (1 - self.dropout_factor[i - 1]) * self.mlp_layers[-1].output
                dropout_layer_input = self.dropout_layers[-1].dropout_output

            if do_maxout == False:
                dropout_layer = DropoutHiddenLayer(rng=numpy_rng,
                                        input=dropout_layer_input,
                                        n_in=input_size,
                                        n_out=hidden_layers_sizes[i],
                                        activation= activation,
                                        dropout_factor=self.dropout_factor[i])
                sigmoid_layer = HiddenLayer(rng=numpy_rng,
                                        input=layer_input,
                                        n_in=input_size,
                                        n_out=hidden_layers_sizes[i],
                                        activation=activation,
                                        W=dropout_layer.W, b=dropout_layer.b)
            else:
                dropout_layer = DropoutHiddenLayer(rng=numpy_rng,
                                        input=dropout_layer_input,
                                        n_in=input_size,
                                        n_out=hidden_layers_sizes[i] * pool_size,
                                        activation= (lambda x: 1.0*x),
                                        dropout_factor=self.dropout_factor[i],
                                        do_maxout = True, pool_size = pool_size)
                sigmoid_layer = HiddenLayer(rng=numpy_rng,
                                        input=layer_input,
                                        n_in=input_size,
                                        n_out=hidden_layers_sizes[i] * pool_size,
                                        activation= (lambda x: 1.0*x),
                                        W=dropout_layer.W, b=dropout_layer.b,
                                        do_maxout = True, pool_size = pool_size)
            # add the layer to our list of layers
            self.mlp_layers.append(sigmoid_layer)
            self.dropout_layers.append(dropout_layer)
            self.params.extend(dropout_layer.params)
            self.delta_params.extend(dropout_layer.delta_params)
        # We now need to add a logistic layer on top of the MLP
        self.dropout_logLayer = LogisticRegression(
                                 input=self.dropout_layers[-1].dropout_output,
                                 n_in=hidden_layers_sizes[-1], n_out=n_outs)

        self.logLayer = LogisticRegression(
                         input=(1 - self.dropout_factor[-1]) * self.mlp_layers[-1].output,
                         n_in=hidden_layers_sizes[-1], n_out=n_outs,
                         W=self.dropout_logLayer.W, b=self.dropout_logLayer.b)

        self.dropout_layers.append(self.dropout_logLayer)
        self.mlp_layers.append(self.logLayer)
        self.params.extend(self.dropout_logLayer.params)
        self.delta_params.extend(self.dropout_logLayer.delta_params)

        # compute the cost
        self.finetune_cost = self.dropout_logLayer.negative_log_likelihood(self.y)
        self.errors = self.logLayer.errors(self.y)

        self.output = self.logLayer.prediction();
        self.features = self.mlp_layers[-2].output;
        self.features_dim = self.mlp_layers[-2].n_out

        if self.l1_reg is not None:
            self.__l1Regularization__();

        if self.l2_reg is not None:
            self.__l2Regularization__();



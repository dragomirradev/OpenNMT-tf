"""RNN functions and classes for TensorFlow 2.0."""

import tensorflow as tf

from opennmt.layers import common


def _register_keras_custom_object(cls):
  tf.keras.utils.get_custom_objects()[cls.__name__] = cls
  return cls


@_register_keras_custom_object
class RNNCellWrapper(common.LayerWrapper):
  """A wrapper for RNN cells."""

  def __init__(self,
               cell,
               input_dropout=0,
               output_dropout=0,
               residual_connection=False,
               **kwargs):
    """Initializes the wrapper.

    Args:
      cell: The cell to wrap.
      input_dropout: The probability to drop units in the cell input.
      output_dropout: The probability to drop units in the cell output.
      residual_connection: Add the inputs to cell outputs (if their shape are
        compatible).
      kwargs: Additional layer arguments.
    """
    super(RNNCellWrapper, self).__init__(
        cell,
        input_dropout=input_dropout,
        output_dropout=output_dropout,
        residual_connection=residual_connection,
        **kwargs)
    self.cell = cell

  @property
  def state_size(self):
    """The cell state size."""
    return self.cell.state_size

  @property
  def output_size(self):
    """The cell output size."""
    return self.cell.output_size

  def get_initial_state(self, inputs=None, batch_size=None, dtype=None):
    """Returns the initial cell state."""
    return self.cell.get_initial_state(
        inputs=inputs, batch_size=batch_size, dtype=dtype)


class _StackedRNNCells(tf.keras.layers.StackedRNNCells):

  # To pass the training flag to the cell, tf.keras.layers.RNN checks that the
  # cell call method explicitly takes the "training" argument, which
  # tf.keras.layers.StackedRNNCells do not.
  # See https://github.com/tensorflow/tensorflow/issues/32586
  def call(self, inputs, states, constants=None, training=None, **kwargs):
    kwargs["training"] = training
    return super(_StackedRNNCells, self).call(inputs, states, constants=constants, **kwargs)


def make_rnn_cell(num_layers,
                  num_units,
                  dropout=0,
                  residual_connections=False,
                  cell_class=None,
                  **kwargs):
  """Convenience function to build a multi-layer RNN cell.

  Args:
    num_layers: The number of layers.
    num_units: The number of units in each layer.
    dropout: The probability to drop units in each layer output.
    residual_connections: If ``True``, each layer input will be added to its output.
    cell_class: The inner cell class or a callable taking :obj:`num_units` as
      argument and returning a cell. Defaults to a LSTM cell.
    kwargs: Additional arguments passed to the cell constructor.

  Returns:
    A ``tf.keras.layers.StackedRNNCells`` instance.

  See Also:
    :class:`opennmt.layers.RNNCellWrapper`
  """
  if cell_class is None:
    cell_class = tf.keras.layers.LSTMCell
  cells = []
  for _ in range(num_layers):
    cell = cell_class(num_units, **kwargs)
    if dropout > 0 or residual_connections:
      cell = RNNCellWrapper(
          cell, output_dropout=dropout, residual_connection=residual_connections)
    cells.append(cell)
  return _StackedRNNCells(cells)


class RNN(tf.keras.layers.Layer):
  """A generic RNN layer."""

  def __init__(self, cell, bidirectional=False, reducer=None, **kwargs):
    """Initializes the layer.

    Args:
      cell: The RNN cell to use.
      bidirectional: Make this layer bidirectional.
      reducer: A :class:`opennmt.layers.Reducer` instance to merge
        bidirectional states and outputs.
      kwargs: Additional layer arguments.

    See Also:
      :func:`opennmt.layers.make_rnn_cell`
    """
    super(RNN, self).__init__(**kwargs)
    self.reducer = reducer
    self.rnn = tf.keras.layers.RNN(cell, return_sequences=True, return_state=True)
    if bidirectional:
      self.rnn = tf.keras.layers.Bidirectional(self.rnn, merge_mode=None)

  def call(self, *args, **kwargs):  # pylint: disable=arguments-differ
    """Forwards the arguments to the RNN layer.

    Args:
      *args: Positional arguments of the RNN layer.
      **kwargs: Keyword arguments of the RNN layer.

    Returns:
      A tuple with the output sequences and the states.
    """
    outputs = self.rnn(*args, **kwargs)
    if isinstance(self.rnn, tf.keras.layers.Bidirectional):
      sequences = outputs[0:2]
      states = outputs[2:]
      fwd_states = states[:len(states)//2]
      bwd_states = states[len(states)//2:]
      if self.reducer is not None:
        sequences = self.reducer(sequences)
        states = tuple(self.reducer.zip_and_reduce(fwd_states, bwd_states))
      else:
        sequences = tuple(sequences)
        states = (fwd_states, bwd_states)
    else:
      sequences = outputs[0]
      states = tuple(outputs[1:])
    return sequences, states

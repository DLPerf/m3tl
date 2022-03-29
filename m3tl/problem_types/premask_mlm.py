# AUTOGENERATED! DO NOT EDIT! File to edit: source_nbs/12_9_problem_type_premask_mlm.ipynb (unless otherwise specified).

__all__ = ['PreMaskMLM', 'premask_mlm_get_or_make_label_encoder_fn', 'premask_mlm_label_handling_fn']

# Cell
import numpy as np
import tensorflow as tf
from loguru import logger
from ..base_params import BaseParams
from .utils import (empty_tensor_handling_loss,
                                      nan_loss_handling, pad_to_shape)
from ..special_tokens import PREDICT
from ..utils import gather_indexes, get_phase, load_transformer_tokenizer
from transformers import TFSharedEmbeddings


# Cell

class PreMaskMLM(tf.keras.Model):
    def __init__(self, params: BaseParams, problem_name: str, input_embeddings: tf.Tensor=None, share_embedding=False) -> None:
        super(PreMaskMLM, self).__init__(name=problem_name)
        self.params = params
        self.problem_name = problem_name

        # same as masklm
        if share_embedding is False:
            self.vocab_size = self.params.bert_config.vocab_size
            self.share_embedding = False
        else:
            self.vocab_size = input_embeddings.shape[0]
            embedding_size = input_embeddings.shape[-1]
            share_valid = (self.params.bert_config.hidden_size ==
                        embedding_size)
            if not share_valid and self.params.share_embedding:
                logger.warning(
                    'Share embedding is enabled but hidden_size != embedding_size')
            self.share_embedding = self.params.share_embedding & share_valid

        if self.share_embedding:
            self.share_embedding_layer = TFSharedEmbeddings(
                vocab_size=self.vocab_size, hidden_size=input_embeddings.shape[1])
            self.share_embedding_layer.build([1])
            self.share_embedding_layer.weight = input_embeddings
        else:
            self.share_embedding_layer = tf.keras.layers.Dense(self.vocab_size)

    def call(self, inputs):
        mode = get_phase()
        features, hidden_features = inputs

        # masking is done inside the model
        seq_hidden_feature = hidden_features['seq']
        if mode != PREDICT:
            positions = features['{}_masked_lm_positions'.format(self.problem_name)]

            # gather_indexes will flatten the seq hidden_states, we need to reshape
            # back to 3d tensor
            input_tensor = gather_indexes(seq_hidden_feature, positions)
            shape_tensor = tf.shape(positions)
            shape_list = tf.concat([shape_tensor, [seq_hidden_feature.shape.as_list()[-1]]], axis=0)
            input_tensor = tf.reshape(input_tensor, shape=shape_list)
            # set_shape to determin rank
            input_tensor.set_shape(
                [None, None, seq_hidden_feature.shape.as_list()[-1]])
        else:
            input_tensor = seq_hidden_feature
        if self.share_embedding:
            mlm_logits = self.share_embedding_layer(
                input_tensor, mode='linear')
        else:
            mlm_logits = self.share_embedding_layer(input_tensor)
        if mode != PREDICT:
            mlm_labels = features['{}_masked_lm_ids'.format(self.problem_name)]
            mlm_labels.set_shape([None, None])
            mlm_labels = pad_to_shape(from_tensor=mlm_labels, to_tensor=mlm_logits, axis=1)
            # compute loss
            mlm_loss = empty_tensor_handling_loss(
                mlm_labels,
                mlm_logits,
                tf.keras.losses.sparse_categorical_crossentropy
            )
            loss = nan_loss_handling(mlm_loss)
            self.add_loss(loss)

        return tf.nn.softmax(mlm_logits)

# Cell
def premask_mlm_get_or_make_label_encoder_fn(params: BaseParams, problem, mode, label_list, *args, **kwargs):
    tok = load_transformer_tokenizer(tokenizer_name=params.transformer_tokenizer_name, load_module_name=params.transformer_tokenizer_loading)
    params.set_problem_info(problem=problem, info_name='num_classes', info=params.bert_config.vocab_size)
    return tok


# Cell
def premask_mlm_label_handling_fn(target: str, label_encoder=None, tokenizer=None, decoding_length=None, *args, **kwargs) -> dict:

    modal_name = kwargs['modal_name']
    modal_type = kwargs['modal_type']
    problem = kwargs['problem']
    max_predictions_per_seq = 20

    if modal_type != 'text':
        return {}

    tokenized_dict = kwargs['tokenized_inputs']

    # create mask lm features
    mask_lm_dict = tokenizer(target,
                             truncation=True,
                             is_split_into_words=True,
                             padding='max_length',
                             max_length=max_predictions_per_seq,
                             return_special_tokens_mask=False,
                             add_special_tokens=False,)

    mask_token_id = tokenizer(
        '[MASK]', add_special_tokens=False, is_split_into_words=False)['input_ids'][0]
    masked_lm_positions = [i for i, input_id in enumerate(
        tokenized_dict['input_ids']) if input_id == mask_token_id]
    # pad masked_lm_positions to max_predictions_per_seq
    if len(masked_lm_positions) < max_predictions_per_seq:
        masked_lm_positions = masked_lm_positions + \
            [0 for _ in range(max_predictions_per_seq -
                              len(masked_lm_positions))]
    masked_lm_positions = masked_lm_positions[:max_predictions_per_seq]
    masked_lm_ids = np.array(mask_lm_dict['input_ids'], dtype='int32')
    masked_lm_weights = np.array(mask_lm_dict['attention_mask'], dtype='int32')
    mask_lm_dict = {'{}_masked_lm_positions'.format(problem): masked_lm_positions,
                    '{}_masked_lm_ids'.format(problem): masked_lm_ids,
                    '{}_masked_lm_weights'.format(problem): masked_lm_weights}
    return mask_lm_dict
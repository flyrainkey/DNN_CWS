# -*- coding: UTF-8 -*-
import tensorflow as tf
import math
import numpy as np
import time
from transform_data_dnn import TransformDataDNN
import constant


class SegDNN:
  def __init__(self, vocab_size, embed_size, skip_window):
    self.TAG_MAPS = np.array([[0, 1], [2, 3], [2, 3], [0, 1]], dtype=np.int32)
    self.TAG_MAPS_TF = tf.constant(self.TAG_MAPS, dtype=tf.int32)
    self.vocab_size = vocab_size
    self.embed_size = embed_size
    self.skip_window = skip_window
    self.alpha = 0.02
    self.h = 300
    self.tags = [0, 1, 2, 3]
    self.tags_count = len(self.tags)
    self.window_length = 2 * self.skip_window + 1
    self.concat_embed_size = self.embed_size * self.window_length
    trans_dnn = TransformDataDNN(self.skip_window)
    self.dictionary = trans_dnn.dictionary
    self.words_batch = trans_dnn.words_batch
    self.tags_batch = trans_dnn.labels_batch
    self.words_count = trans_dnn.words_count
    self.context_count = trans_dnn.context_count
    self.sess = None
    self.x = tf.placeholder(tf.float32, shape=[self.concat_embed_size, None], name='x')
    self.map_matrix = tf.placeholder(tf.float32, shape=[4, None], name='smm')
    self.sentence_matrix = tf.placeholder(tf.float32, shape=[None, 4], name='sm')
    self.embeddings = tf.Variable(tf.random_uniform([self.vocab_size, self.embed_size], -1.0, 1.0), name='embeddings')
    self.w2 = tf.Variable(
      tf.truncated_normal([self.h, self.concat_embed_size], stddev=1.0 / math.sqrt(self.concat_embed_size)),
      name='w2')
    self.b2 = tf.Variable(tf.zeros([self.h, 1]), name='b2')
    # self.w3 = tf.Variable(
    #  tf.truncated_normal([self.tags_count, self.h], stddev=1.0 / math.sqrt(self.concat_embed_size)),
    #  name='w3')
    self.w3 = tf.Variable(tf.random_normal([self.tags_count, self.h], 0, 1.0 / math.sqrt(self.h)), name='w3')
    self.b3 = tf.Variable(tf.zeros([self.tags_count, 1]), name='b3')
    self.word_score = tf.add(tf.matmul(self.w3, tf.sigmoid(tf.add(tf.matmul(self.w2, self.x), self.b2))), self.b3)
    self.params = [self.w2, self.w3, self.b2, self.b3]
    self.A = tf.Variable([[1, 1, 0, 0], [0, 0, 1, 1], [0, 0, 1, 1], [1, 1, 0, 0]], dtype=tf.float32, name='A')
    self.init_A = tf.Variable([1, 1, 0, 0], dtype=tf.float32, name='init_A')
    self.Ap = tf.placeholder(tf.float32, shape=self.A.get_shape())
    self.init_Ap = tf.placeholder(tf.float32, shape=self.init_A.get_shape())
    self.embedp = tf.placeholder(tf.float32, shape=[None, self.embed_size])
    self.embed_index = tf.placeholder(tf.int32, shape=[None])
    self.update_embed_op = tf.scatter_add(self.embeddings, self.embed_index, self.embedp)
    # self.optimizer = tf.train.GradientDescentOptimizer(-self.alpha)
    self.optimizer = tf.train.AdamOptimizer(-self.alpha)
    self.update_A_op = self.A.assign_add(self.Ap)
    self.update_init_A_op = self.init_A.assign_add(self.init_Ap)
    self.loss = tf.reduce_sum(tf.multiply(self.map_matrix, self.word_score))
    self.scores = tf.multiply(self.map_matrix, self.word_score)
    self.grad_embed = tf.gradients(tf.multiply(self.map_matrix, self.word_score), self.x)
    self.train_loss = self.optimizer.minimize(self.loss, var_list=self.params)
    self.indices = tf.placeholder(tf.int32, shape=[None, 2])
    self.shape = tf.placeholder(tf.int32, shape=[2])
    self.values = tf.placeholder(tf.float32, shape=[None])
    self.gen_map = tf.sparse_to_dense(self.indices, self.shape, self.values, validate_indices=False)
    self.sentence_holder = tf.placeholder(tf.int32, shape=[None, 3])
    self.tags_holder = tf.placeholder(tf.int32, shape=[None])
    self.lookup_op = tf.nn.embedding_lookup(self.embeddings, self.sentence_holder)

  def train(self):
    """
    用于训练模型
    :param vocab_size:
    :param embed_size:
    :param skip_window:
    :return:
    """

    print('start...')

    self.sess = tf.Session()
    saver = tf.train.Saver([self.embeddings, self.A].extend(self.params))
    train_writer = tf.summary.FileWriter('logs', self.sess.graph)
    init = tf.global_variables_initializer()
    init.run(session=self.sess)
    self.sess.graph.finalize()
    loss = []
    count = 10
    for i in range(count):
      loss.append(self.train_exe() / 100000000)
      saver.save(self.sess, 'tmp/model%d.ckpt' % i)
    print(loss)
    train_writer.flush()
    self.sess.close()

  def train_exe(self):
    start = time.time()
    time_all = 0.0
    start_c = 0
    # print(tf.GraphKeys.TRAINABLE_VARIABLES.count())
    for sentence_index, (sentence, tags) in enumerate(zip(self.words_batch, self.tags_batch)):
      start_s = time.time()
      self.train_sentence(sentence, tags, len(tags))
      start_c += time.time() - start_s
      time_all += time.time() - start_s

      if sentence_index % 2000 == 0:
        print('s:' + str(sentence_index))
        print(start_c)
        print(time_all / 60)
        start_c = 0

    loss = 0.0
    for sentence_index, (sentence, tags) in enumerate(zip(self.words_batch, self.tags_batch)):
      loss += self.cal_sentence_loss(sentence, tags, len(tags))
    print(loss)
    print(time.time() - start)
    return math.fabs(loss)

  def train_sentence(self, sentence, tags, length):
    sentence_embeds = self.sess.run(self.lookup_op, feed_dict={self.sentence_holder: sentence}).reshape(
      [length, self.concat_embed_size]).T
    sentence_scores = self.sess.run(self.word_score, feed_dict={self.x: sentence_embeds}).T

    init_A_val = self.init_A.eval(session=self.sess)
    A_val = self.A.eval(session=self.sess)
    current_tags = self.viterbi(sentence_scores, A_val, init_A_val)  # 当前参数下的最优路径
    diff_tags = np.subtract(tags, current_tags)
    update_index = np.where(diff_tags != 0)[0]  # 标签不同的字符位置
    update_length = len(update_index)

    # 完全正确
    if update_length == 0:
      return 0, 0

    update_pos_tags = np.array(tags, dtype=np.int32)[update_index]  # 需要更新的字符的位置对应的正确字符标签
    update_neg_tags = current_tags[update_index]  # 需要更新的字符的位置对应的错误字符标签
    update_embed = sentence_embeds[:, update_index]
    sparse_indices = np.stack(
      [np.concatenate([update_pos_tags, update_neg_tags], axis=-1), np.tile(np.arange(update_length), [2])], axis=-1)
    sparse_values = np.concatenate([np.ones(update_length), -1 * np.ones(update_length)])
    output_shape = [4, update_length]
    sentence_matrix = self.sess.run(self.gen_map, feed_dict={self.indices: sparse_indices, self.shape: output_shape,
                                                             self.values: sparse_values})

    self.update_params(sentence_matrix, update_embed, sentence[update_index], update_length)
    # 更新转移矩阵
    A_update, init_A_update, update_init = self.gen_update_A(tags, current_tags)
    if update_init:
      self.sess.run(self.update_init_A_op, feed_dict={self.init_Ap: self.alpha * init_A_update})
    self.sess.run(self.update_A_op, {self.Ap: self.alpha * A_update})

  def update_params(self, sen_matrix, embeds, embed_index, update_length):
    """
    
    :param sen_matrix: 4*length
    :param embeds: 150*length
    :param embed_index: length*3
    :param update_length: 
    :return: 
    """
    self.sess.run(self.train_loss, feed_dict={self.x: embeds, self.map_matrix: sen_matrix})
    # grad = self.sess.run(self.grad_embed, feed_dict={self.x: embeds, self.map_matrix: sen_matrix})
    # grad = grad.reshape([update_length * self.window_length, self.embed_size])
    # self.sess.run(self.grad_embed,feed_dict={self.x:embeds,self.map_matrix:sen_matrix})

    for i in range(update_length):
      grad = self.sess.run(self.grad_embed, feed_dict={self.x: np.expand_dims(embeds[:, i], 1),
                                                       self.map_matrix: np.expand_dims(sen_matrix[:, i], 1)})[0]
      self.sess.run(self.update_embed_op,
                    feed_dict={self.embedp: self.alpha * grad.reshape([self.window_length, self.embed_size]),
                               self.embed_index: embed_index[i, :]})

  def gen_update_A(self, correct_tags, current_tags):
    A_update = np.zeros([4, 4], dtype=np.float32)
    init_A_update = np.zeros([4], dtype=np.float32)
    before_corr = correct_tags[0]
    before_curr = current_tags[0]
    update_init = False

    if before_corr != before_curr:
      init_A_update[before_corr] += 1
      init_A_update[before_curr] -= 1
      update_init = True

    for _, (corr_tag, curr_tag) in enumerate(zip(correct_tags[1:], current_tags[1:])):
      if corr_tag != curr_tag or before_corr != before_curr:
        A_update[before_corr, corr_tag] += 1
        A_update[before_curr, curr_tag] -= 1
      before_corr = corr_tag
      before_curr = curr_tag

    return A_update, init_A_update, update_init

  def viterbi(self, emission, A, init_A):
    """
    维特比算法的实现，
    :param emission: 发射概率矩阵，对应于本模型中的分数矩阵
    :param A: 转移概率矩阵
    :return:
    """

    path = np.array([[0], [1]], dtype=np.int32)
    path_score = np.array([[init_A[0] + emission[0, 0]], [init_A[1] + emission[0, 1]]], dtype=np.float32)

    for line_index in range(1, emission.shape[0]):
      last_index = path[:, -1]
      cur_index = self.TAG_MAPS[last_index]  # 当前所有路径的可选的标记矩阵，2x2
      # 当前所有可能路径的分值
      cur_res = A[last_index, cur_index] + emission[line_index, cur_index] + np.expand_dims(path_score[:, -1], 1)
      cur_max_index = np.argmax(cur_res, 1)
      path = np.insert(path, [path.shape[1]], np.expand_dims(np.choose(cur_max_index, cur_index.T), 1), 1)
      path_score = np.insert(path_score, [path_score.shape[1]], np.expand_dims(np.choose(cur_max_index, cur_res.T), 1),
                             1)

    return path[np.argmax(path_score[:, -1]), :]

  def cal_sentence_loss(self, sentence, tags, length):
    sentence_embeds = self.sess.run(self.lookup_op, feed_dict={self.sentence_holder: sentence}).reshape(
      [length, self.concat_embed_size]).T
    sentence_scores = self.sess.run(self.word_score, feed_dict={self.x: sentence_embeds}).T

    init_A_val = self.init_A.eval(session=self.sess)
    A_val = self.A.eval(session=self.sess)
    current_tags = self.viterbi(sentence_scores, A_val, init_A_val)  # 当前参数下的最优路径
    loss = 0.0
    before_corr = 0
    before_cur = 0
    for index, (cur_tag, corr_tag, scores) in enumerate(zip(current_tags, tags, sentence_scores)):
      if index == 0:
        loss += scores[corr_tag] + init_A_val[corr_tag] - scores[cur_tag] - init_A_val[cur_tag]
      loss += scores[corr_tag] + A_val[before_corr, corr_tag] - scores[cur_tag] - A_val[before_cur, cur_tag]
      before_cur = cur_tag
      before_corr = corr_tag

    return loss

  def sentence2index(self, sentence):
    index = []
    for word in sentence:
      if word not in self.dictionary:
        index.append(0)
      else:
        index.append(self.dictionary[word])

    return index

  def index2seq(self, indices):
    ext_indices = [0] * self.skip_window
    ext_indices.extend(indices + [0] * self.skip_window)
    seq = []
    for index in range(self.skip_window, len(ext_indices) - self.skip_window):
      seq.append(ext_indices[index - self.skip_window: index + self.skip_window + 1])

    return seq

  def tags2words(self, sentence, tags):
    print(tags)
    words = []
    word = ''
    for tag_index, tag in enumerate(tags):
      if tag == 0:
        words.append(sentence[tag_index])
      elif tag == 1:
        word = sentence[tag_index]
      elif tag == 2:
        word += sentence[tag_index]
      else:
        words.append(word + sentence[tag_index])
        word = ''
    # 处理最后一个标记为I的情况
    if word != '':
      words.append(word)

    return words

  def seg(self, sentence):
    tf.reset_default_graph()
    x = tf.placeholder(tf.float32, shape=[self.concat_embed_size, None], name='x')
    embeddings = tf.Variable(tf.random_uniform([self.vocab_size, self.embed_size], -1.0, 1.0), name='embeddings')
    w2 = tf.Variable(
      tf.truncated_normal([self.h, self.concat_embed_size], stddev=1.0 / math.sqrt(self.concat_embed_size)),
      name='w2')
    b2 = tf.Variable(tf.zeros([self.h, 1]), name='b2')
    w3 = tf.Variable(tf.truncated_normal([self.tags_count, self.h], stddev=1.0 / math.sqrt(self.concat_embed_size)),
                     name='w3')
    b3 = tf.Variable(tf.zeros([self.tags_count, 1]), name='b3')
    word_score = tf.matmul(w3, tf.sigmoid(tf.matmul(w2, x) + b2)) + b3
    A = tf.Variable(
      [[1, 1, 0, 0], [0, 0, 1, 1], [0, 0, 1, 1], [1, 1, 0, 0]], dtype=tf.float32, name='A')
    init_A = tf.Variable([1, 1, 0, 0], dtype=tf.float32, name='init_A')
    saver = tf.train.Saver()
    with tf.Session() as sess:
      saver.restore(sess, 'tmp/model0.ckpt')
      seq = self.index2seq(self.sentence2index(sentence))
      sentence_embeds = tf.nn.embedding_lookup(embeddings, seq).eval().reshape(
        [len(sentence), self.concat_embed_size]).T
      sentence_scores = sess.run(word_score, feed_dict={x: sentence_embeds}).T
      init_A_val = init_A.eval()
      A_val = A.eval()
      #print(A_val)
      # print(init_A_val)
      current_tags = self.viterbi(sentence_scores, A_val, init_A_val)
      print(sentence_embeds[1])
      #print(sentence_scores)
      return self.tags2words(sentence, current_tags)


if __name__ == '__main__':
  embed_size = 50
  cws = SegDNN(constant.VOCAB_SIZE, embed_size, constant.DNN_SKIP_WINDOW)
  #cws.train()
  print(cws.seg('小明来自南京师范大学'))
  # print(cws.seg('小明是上海理工大学的学生'))
  # print(cws.seg('我爱北京天安门'))

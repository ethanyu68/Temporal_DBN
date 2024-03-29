"""
This class implement a Discrimination Conditional RBM, a CRBM combines with a logistic regressive layer.
This principle allow us to train a CRBM in a discriminative way, in other words, with respect to a supervised criterion.
@author Lisa Lab : DBN (Deep Belief Network) class
@modification Francois Lasson : CERV Brest France
@mail : francois.lasson@gmail.com
"""
#Numpy and Theano library
import numpy as np
import theano
import theano.tensor as T
#theano Random
from theano.sandbox.rng_mrg import MRG_RandomStreams
#Use to compute learning time
import timeit
#Use to save trained model or dataset
import _pickle as cPickle
#This class used to generate dataset readable by RBMs from BVH files
from motion import generate_dataset
#Import classes for crbm and logistic regression layer
from Temporal_DBN.code.crbm import CRBM
from logistic_sgd import LogisticRegression

class LOGISTIC_CRBM(object):
    """CRBM + LogisticRegression : This principle is used to train CRBM with respect to a supervised criterion
    This model is obtain by adding a logistic regression on top a CRBM and used it for classification.
    CRBM is pre-trained by the constrastive divergence algorithm, after this architecture is fine-tuned.
    """
    def __init__(self, numpy_rng=None, theano_rng=None,
                 n_input=2, n_hidden=50, n_label=3, n_delay=6, forward=3,freq=1):
        """
        :type numpy_rng: np.random.RandomState
        :param numpy_rng: numpy random number generator used to draw initial weights

        :type theano_rng: theano.tensor.shared_randomstreams.RandomStreams
        :param theano_rng: Theano random generator; if None is given one is
                           generated based on a seed drawn from `rng`

        :type n_input: int
        :param n_input: dimension of the input to the DBN

        :type n_hidden: int
        :param n_hidden: intermediate layer size

        :type n_label: int
        :param n_label: dimension of the output of the network (label layers)

        :type n_delay: int
        :param n_delay: number of past visible layer in the CRBM
        """

        self.params = []

        self.n_input = n_input
        self.n_hidden = n_hidden
        self.n_label = n_label
        self.delay = n_delay
        self.freq = freq
        self.forward = forward

        if numpy_rng is None:
            # create a number generator
            numpy_rng = np.random.RandomState(1234)
        if not theano_rng:
            theano_rng = MRG_RandomStreams(numpy_rng.randint(2 ** 30))


        # allocate symbolic variables for the data
        self.x = T.matrix('x')  # the data is presented as rasterized images
        self.x_history = T.matrix('x_history') #memory : past visible is a recopy of visible layer
        self.y = T.lvector('y')  # the labels are presented as 1D vector of [int] labels (digit)

        # Construct an CRBM that shared weights with this layer
        self.crbm_layer = CRBM(numpy_rng=numpy_rng, theano_rng=theano_rng,
                               input=self.x, input_history = self.x_history,
                               n_visible=n_input, n_hidden=n_hidden, delay =n_delay, forward=forward,freq=freq)

        self.params.append(self.crbm_layer.W)
        self.params.append(self.crbm_layer.B)
        self.params.append(self.crbm_layer.hbias)

        # We now need to add a logistic layer on top of the MLP
        input_logistic = T.nnet.relu(T.dot(self.x, self.crbm_layer.W)+ T.dot(self.x_history, self.crbm_layer.B) + self.crbm_layer.hbias)
        self.logLayer = LogisticRegression(
            input=input_logistic,
            n_in=n_hidden,
            n_out=n_label)

        self.params.extend(self.logLayer.params)

        # compute the cost for second phase of training, defined as the
        # negative log likelihood of the logistic regression (output) layer
        self.finetune_cost = self.logLayer.negative_log_likelihood(self.y)

        # compute the gradients with respect to the model parameters
        # symbolic variable that points to the number of errors made on the
        # minibatch given by self.x and self.y
        self.errors = self.logLayer.errors(self.y)  # error of LOG regression

    def build_finetune_functions(self, dataset_train, labelset_train, seqlen_train,
                                 dataset_validation, labelset_validation, seqlen_validation,
                                 dataset_test, labelset_test, seqlen_test ,
                                 batch_size,learning_rate):
        '''Generates a function `train` that implements one step of
        finetuning, a function `validate` that computes the error on a
        batch from the validation set, and a function `test` that
        computes the error on a batch from the testing set

        :type datasets: list of pairs of theano.tensor.TensorType
        :param datasets: It is a list that contain all the datasets;
                        it has to contain three pairs, `train`,
                        `valid`, `test` in this order, where each pair
                        is formed of two Theano variables, one for the
                        datapoints, the other for the labels
        :type batch_size: int
        :param batch_size: size of a minibatch
        :type learning_rate: float
        :param learning_rate: learning rate used during finetune stage
        '''

        # compute number of minibatches for training, validation and testing
        #@Info : why -self.delay*len(seqlen) ? : For each file in each dataset, (self.delay*self.freq) frames are used to initialize crbm memory (past visibles layer)
        n_valid_batches = (dataset_validation.get_value(borrow=True).shape[0]-(self.delay*self.freq)*len(seqlen_validation))//batch_size
        n_test_batches = (dataset_test.get_value(borrow=True).shape[0]-(self.delay*self.freq)*len(seqlen_test))//batch_size
        n_dim = dataset_validation.get_value(borrow=True).shape[1]

        index_forward = T.lvector()    # index to forward
        index_history = T.lvector()  # index to history
        index = T.lvector() # index to data

        # compute the gradients with respect to the model parameters
        gparams = T.grad(self.finetune_cost, self.params)

        # compute list of fine-tuning updates
        updates = []
        for param, gparam in zip(self.params, gparams):
            updates.append((param, param - gparam * learning_rate))

        train_fn = theano.function(
            inputs=[index_forward, index_history,index],
            outputs=self.finetune_cost,
            updates=updates,
            givens={
                self.x: dataset_train[index_forward].reshape((batch_size, self.forward *n_dim)),
                self.x_history : dataset_train[index_history].reshape((batch_size, self.delay * n_dim)),
                self.y: labelset_train[index]
            }
        )

        test_score_i = theano.function(
            [index_forward, index_history,index],
            self.errors,
            givens={
                self.x: dataset_test[index_forward].reshape((batch_size, self.forward *n_dim)),
                self.x_history: dataset_test[index_history].reshape((batch_size, self.delay * n_dim)),
                self.y: labelset_test[index]
            }
        )

        valid_score_i = theano.function(
            [index_forward, index_history,index],
            self.errors,
            givens={
                self.x: dataset_validation[index_forward].reshape((batch_size, self.forward *n_dim)),
                self.x_history: dataset_validation[index_history].reshape((batch_size, self.delay * n_dim)),
                self.y: labelset_validation[index]
            }
        )

        # Create a function that scans the entire validation set
        def valid_score():
            datasetindex = []
            last = 0
            for s in seqlen_validation:
                datasetindex += range(last + (self.delay*self.freq), last + s)
                last += s
            permindex = np.array(datasetindex)
            valid_score_out = []
            for batch_index in range(n_valid_batches):
                data_idx = permindex[batch_index * batch_size:(batch_index + 1) * batch_size]
                visi_idx = np.array([data_idx + (n * self.freq) for n in range(0, self.forward)]).T  # Due to memory (past visible)
                hist_idx = np.array([data_idx-(n*self.freq) for n in range(1, self.delay + 1)]).T
                valid_score_out.append(valid_score_i(visi_idx.ravel(), hist_idx.ravel(),data_idx))
            return valid_score_out

        # Create a function that scans the entire test set
        def test_score():
            datasetindex = []
            last = 0
            for s in seqlen_test:
                datasetindex += range(last + (self.delay*self.freq), last + s)
                last += s
            permindex = np.array(datasetindex)
            test_score_out = []
            for batch_index in range(n_test_batches):
                data_idx = permindex[batch_index * batch_size:(batch_index + 1) * batch_size]
                visi_idx = np.array([data_idx + (n * self.freq) for n in range(0, self.forward)]).T  # Due to memory (past visible)
                hist_idx = np.array([data_idx-(n*self.freq) for n in range(1, self.delay + 1)]).T
                test_score_out.append(test_score_i(visi_idx.ravel(), hist_idx.ravel(),data_idx))
            return test_score_out

        return train_fn, valid_score, test_score

    """recognize_dataset is a function used to recognize a dataset using a mini_batch"""
    def recognize_dataset(self, dataset_test = None, seqlen=None, batch_size =100) :
        #Here, we don't ignore the 6 first frames cause we want to test recognition performance on each frames of the test dataset
        n_test_batches = (dataset_test.get_value(borrow=True).shape[0]-(self.delay+self.forward)*self.freq*len(seqlen)) // batch_size
        n_dim = dataset_test.get_value(borrow=True).shape[1]

        # allocate symbolic variables for the data
        index_forward = T.lvector()    # index to a [mini]batch
        index_hist = T.lvector()  # index to history

        input_log = T.nnet.sigmoid(T.dot(self.x, self.crbm_layer.W)+ T.dot(self.x_history, self.crbm_layer.B) + self.crbm_layer.hbias)
        prob = self.logLayer.p_y_given_x
        prediction = self.logLayer.y_pred

        print_prediction = theano.function(
            [index_forward, index_hist],
            [prediction, prob],
            givens={ self.x:dataset_test[index_forward].reshape((batch_size, self.forward * n_dim)),
                     self.x_history:dataset_test[index_hist].reshape((batch_size, self.delay * n_dim))
                    },
            name='print_prediction'
            )
        # valid starting indices
        datasetindex = range(self.delay*self.freq, dataset_test.get_value(borrow=True).shape[0]-(self.forward-1+self.delay)*self.freq)
        permindex = np.array(datasetindex)

        predict = []
        probability = []
        for batch_index in range(n_test_batches):
            data_idx = permindex[batch_index * batch_size : (batch_index + 1) * batch_size]
            visi_idx = np.array([data_idx + n*self.freq for n in range(0, self.forward)]).T
            hist_idx = np.array([data_idx - n*self.freq for n in range(1, self.delay + 1)]).T
            pred, prob = print_prediction(visi_idx.ravel(), hist_idx.ravel())
            predict.append(pred)
            probability.append(prob)
            '''
            # print result of each frame
            for index_in_batch in range(batch_size) :            
                print("(frame %d):" %(batch_index*batch_size+index_in_batch+1))
                print("%% of recognition for each pattern : ")
                print (print_prediction(data_idx, hist_idx.ravel())[1][index_in_batch])
                print ("So, recognized pattern is :")
                print (print_prediction(data_idx, hist_idx.ravel())[0][index_in_batch])
                print ("-----------")
                '''
        predict = np.array(predict).ravel()
        prob = np.array(probability).reshape([-1,2])
        return predict, probability

    def predict_label(self, crbm_visible, crbm_past_visible) :
        #Define a theano function
        visible = T.vector()
        past_visible = T.vector()
        input_log = T.nnet.sigmoid(T.dot(visible, self.crbm_layer.W)+ T.dot(past_visible, self.crbm_layer.B) + self.crbm_layer.hbias)
        output_log = T.nnet.softmax(T.dot(input_log, self.logLayer.W) + self.logLayer.b)
        prediction = T.argmax(output_log, axis=1)[0]
        f = theano.function([visible, past_visible],prediction)
        return f(crbm_visible, crbm_past_visible)

def create_train_LogisticCrbm(
                    finetune_lr=0.1, pretraining_epochs=100,
                    pretrain_lr=1e-3, k=1, training_epochs=100,
                    dataset_train=None, labelset_train=None, seqlen_train = None,
                    dataset_validation=None, labelset_validation=None, seqlen_validation = None,
                    dataset_test=None, labelset_test=None, seqlen_test = None,
                    batch_size=100, number_hidden_crbm=50, n_delay=6, freq=1, n_label=3, forward=3,retrain_crbm = True, log_crbm=None):

    #get datain dimension in order to set CRBM input size
    n_dim = dataset_train.shape[1].eval()

    # numpy random generator
    numpy_rng = np.random.RandomState(123)
    print('... building the model')
    # construct the logistic + crbm

    #########################
    # PRETRAINING THE MODEL # # for test, it's also possible to reload it
    #########################
    if (retrain_crbm):
        log_crbm = LOGISTIC_CRBM(numpy_rng=numpy_rng, n_input=n_dim, n_label = n_label, n_hidden=number_hidden_crbm, n_delay=n_delay, freq=freq,forward=forward)
        print('... pre-training the model')
        cost_crbm = log_crbm.crbm_layer.train(learning_rate=pretrain_lr, training_epochs=pretraining_epochs, dataset=dataset_train, seqlen= seqlen_train, batch_size=batch_size)
        # with open('trained_model/best_log_crbm.pkl','w') as f:
        #   cPickle.dump(log_crbm, f)
    else:
        cost_crbm = None
        log_crbm = log_crbm
        #log_crbm = cPickle.load(open('trained_model/best_log_crbm.pkl'))
        print('... model is pre-trained')

    ########################
    # FINETUNING THE MODEL #
    ########################

    # compute number of minibatches for training, validation and testing
    #@Info : why -self.delay*len(seqlen) ? : For each file in each dataset, log_crbm.delay*log_crbm.freq frames are used to initialize crbm memory (past visibles layer)
    n_train_batches = (dataset_train.shape[0]-((log_crbm.delay+log_crbm.forward)*log_crbm.freq)*len(seqlen_train)) // batch_size


    # get the training, validation and testing function for the model
    print('... getting the finetuning functions')
    train_fn, validate_model, test_model = log_crbm.build_finetune_functions(
                batch_size=batch_size, learning_rate=finetune_lr, dataset_train = dataset_train, labelset_train = theano.shared(np.array(labelset_train)),
                seqlen_train = seqlen_train, dataset_validation = dataset_validation, labelset_validation = theano.shared(np.array(labelset_validation)),
                seqlen_validation = seqlen_validation, dataset_test = dataset_test, labelset_test = theano.shared(np.array(labelset_test)), seqlen_test = seqlen_test)

    print('... finetuning the model')
    # early-stopping parameters
    n_train_batches = n_train_batches.eval()
    patience = 4 * n_train_batches  # look as this many examples regardless
    patience_increase = 2.    # wait this much longer when a new best is found
    improvement_threshold = 0.995  # a relative improvement of this much is
                                   # considered significant
    validation_frequency = min(n_train_batches, patience / 2)
                                  # go through this many
                                  # minibatches before checking the network
                                  # on the validation set; in this case we
                                  # check every epoch

    best_validation_loss = np.inf
    test_score = 0.
    start_time = timeit.default_timer()

    done_looping = False
    epoch = 0

    datasetindex = []
    last = 0
    for s in seqlen_train:
        datasetindex += range(last+(log_crbm.delay*log_crbm.freq), last + s)
        last += s
        permindex = np.array(datasetindex)

    #PER_x and PER_y are two variables used to plot PER evolution
    PER_y_valid = []
    PER_x_valid = []
    PER_y_test = []
    PER_x_test = []
    while (epoch < training_epochs) and (not done_looping): #TODO supprimer le not done_looping pour forcer le bouclage?
        epoch = epoch + 1
        for minibatch_index in range(n_train_batches):
            data_idx = permindex[minibatch_index * batch_size:(minibatch_index + 1) * batch_size]
            visi_idx = np.array([data_idx + (n * log_crbm.freq) for n in range(0, forward )]).T#Due to memory (past visible)
            hist_idx = np.array([data_idx - (n*log_crbm.freq) for n in range(1, log_crbm.delay + 1)]).T
            minibatch_avg_cost = train_fn(visi_idx.ravel(), hist_idx.ravel(),data_idx) #training model : fine tune phase
            iter = (epoch - 1) * n_train_batches + minibatch_index

            if (iter + 1) % (10*validation_frequency) == 0:

                validation_losses = validate_model()
                this_validation_loss = np.mean(validation_losses)
                print(
                    'epoch %i, minibatch %i/%i, validation error %f %%'
                    % (
                        epoch,
                        minibatch_index + 1,
                        n_train_batches,
                        this_validation_loss * 100.
                    )
                )
                PER_x_valid.append(epoch)
                PER_y_valid.append(this_validation_loss * 100.)

                # if we got the best validation score until now
                if this_validation_loss < best_validation_loss:

                    #improve patience if loss improvement is good enough
                    if (this_validation_loss < best_validation_loss * improvement_threshold):
                        patience = max(patience, iter * patience_increase)

                    # save best validation score and iteration number
                    best_validation_loss = this_validation_loss
                    best_iter = iter

                    # test it on the test set
                    test_losses = test_model()
                    test_score = np.mean(test_losses)
                    print(('     epoch %i, minibatch %i/%i, test error of '
                           'best model %f %%') %
                          (epoch, minibatch_index + 1, n_train_batches,
                           test_score * 100.))
                    PER_x_test.append(epoch)
                    PER_y_test.append(test_score * 100.)
            #if patience <= iter:
                #done_looping = True
                #break

    end_time = timeit.default_timer()
    print(
        (
            'Optimization complete with best validation score of %f %%, '
            
            'with test performance %f %%'
        ) % (best_validation_loss * 100., test_score * 100.)
    )
    PER_x_test.append(training_epochs)
    #PER_y_test.append(PER_y_test[-1])
    print ("The fine tuning ran for %.2fm" % ((end_time - start_time)/ 60.))


    return log_crbm #, train_fn,validate_model, test_model




if __name__ == '__main__':
    print("nothing to do, launch python code/tdbn.py")

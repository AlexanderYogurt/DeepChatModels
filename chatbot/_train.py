"""Train seq2seq attention chatbot."""
import time
import numpy as np
from utils import *
import tensorflow as tf


def _train(chatbot, dataset, train_config):
    """ Train chatbot using dataset given by train_config.dataset.
        chatbot: instance of Chatbot.
    """

    with chatbot.sess as sess:
        # Read data into buckets and compute their sizes.
        print ("Reading development and training data (limit: %d)." % train_config.max_train_samples)
        train_set, dev_set = data_utils.read_data(dataset,
                                                  chatbot.buckets,
                                                  max_train_data_size=train_config.max_train_samples)

        # Interpret as: train_buckets_scale[i] == [cumulative] fraction of samples in bucket i or below.
        train_buckets_scale = _get_data_distribution(train_set, chatbot.buckets)

        # This is the training loop.
        step_time, loss = 0.0, 0.0
        previous_losses = []
        try:
            for i_step in range(100000):
                # Sample a random bucket index according to the data distribution,
                # then get a batch of data from that bucket by calling chatbot.get_batch.
                rand = np.random.random_sample()
                bucket_id = min([i for i in range(len(train_buckets_scale)) if train_buckets_scale[i] > rand])

                # Get a batch and make a step.
                start_time = time.time()
                summary, step_loss = _step(sess, chatbot, train_set, bucket_id, False)
                chatbot.train_writer.add_summary(summary, i_step)
                step_time += (time.time() - start_time) / train_config.steps_per_ckpt
                loss      += step_loss / train_config.steps_per_ckpt

                # Once in a while, we save checkpoint, print statistics, and run evals.
                if i_step % train_config.steps_per_ckpt == 0:
                    _run_checkpoint(sess, chatbot, train_config, step_time, loss, previous_losses, dev_set)
                    step_time, loss = 0.0, 0.0
        except (KeyboardInterrupt, SystemExit):
            print("Training halted. Cleaning up . . . ")
            chatbot.train_writer.close()
            # Save checkpoint and zero timer and loss.
            checkpoint_path = os.path.join(train_config.ckpt_dir, "{}.ckpt".format(train_config.data_name))
            # Saves the state of all global variables.
            chatbot.saver.save(sess, checkpoint_path, global_step=chatbot.global_step)
            print("Done.")


def _step(sess, model, train_set, bucket_id, forward_only=False):
    # Recall that target_weights are NOT parameter weights; they are weights in the sense of "weighted average."
    encoder_inputs, decoder_inputs, target_weights = model.get_batch(train_set, bucket_id)

    step_returns = model.step(sess, encoder_inputs, decoder_inputs, target_weights, bucket_id, forward_only)
    summary, gradient_norms, losses, _ = step_returns
    return summary, losses

def _run_checkpoint(sess, model, config, step_time, loss, previous_losses, dev_set):
    # Print statistics for the previous epoch.
    perplexity = np.exp(float(loss)) if loss < 300 else float("inf")
    print("\nglobal step:", model.global_step.eval(), end="  ")
    print("learning rate: %.4f" %  model.learning_rate.eval(), end="  ")
    print("step time: %.2f" % step_time, end="  ")
    print("perplexity: %.2f" % perplexity)

    # Decrease learning rate more aggressively.
    if len(previous_losses) > 4 and loss > min(previous_losses[-4:]):
        sess.run(model.lr_decay_op)
    previous_losses.append(loss)

    # Save checkpoint and zero timer and loss.
    checkpoint_path = os.path.join(config.ckpt_dir, "{}.ckpt".format(config.data_name))
    # Saves the state of all global variables.
    model.saver.save(sess, checkpoint_path, global_step=model.global_step)

    # Run evals on development set and print their perplexity.
    for bucket_id in range(len(model.buckets)):
        if len(dev_set[bucket_id]) == 0:
            print("  eval: empty bucket %d" % (bucket_id))
            continue
        _, eval_loss = _step(sess, model, dev_set, bucket_id, forward_only=True)
        eval_ppx = np.exp(float(eval_loss)) if eval_loss < 300 else float("inf")
        print("  eval: bucket %d perplexity %.2f" % (bucket_id, eval_ppx))
    sys.stdout.flush()

def _get_data_distribution(train_set, buckets):
    # Get number of samples for each bucket (i.e. train_bucket_sizes[1] == num-trn-samples-in-bucket-1).
    train_bucket_sizes = [len(train_set[b]) for b in range(len(buckets))]
    # The total number training samples, excluding the ones too long for our bucket choices.
    train_total_size   = float(sum(train_bucket_sizes))

    # Interpret as: train_buckets_scale[i] == [cumulative] fraction of samples in bucket i or below.
    return [sum(train_bucket_sizes[:i + 1]) / train_total_size
                     for i in range(len(train_bucket_sizes))]



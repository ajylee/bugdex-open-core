from concurrent.futures import Future

from IPython.core.display import HTML, display
import threading
import ipywidgets as widgets
import time
import concurrent.futures


def html_link(href, text=None):
    from html import escape
    if text is None:
        text = href
    return widgets.HTML(f'<a href={escape(href)}>{escape(text)}</a>')


def with_progress_bar(target):
    """
    Adapted from ipywidgets progress bar example

    :param target: Function to run. Function must take progress bar as argument.
    :return: None

    Try it out with::
        a = []
        def work(progress):
            total = 3
            for i in range(total):
                time.sleep(0.1)
                progress.value = float(i+1)/total
            a.append(i)
            return total

        with_progress_bar(work)
        print(a)

    See also: https://stackoverflow.com/questions/6893968/how-to-get-the-return-value-from-a-thread-in-python

    """
    progress = widgets.FloatProgress(value=0.0, min=0.0, max=1.0)
    display(progress)

    with concurrent.futures.ThreadPoolExecutor() as executor:
        future: Future = executor.submit(target, progress)
        return future.result()


def detect_aws_jupyter_type():
    import subprocess as sbp

    whoami = sbp.Popen(['whoami'], stdout=sbp.PIPE).communicate()[0]

    user_to_aws_jupyter_type = {
        'ec2-user': 'notebook-instance',  # notebook-instance runs as root
        'sagemaker-user': 'sagemaker-studio-system',  # from system terminal, studio runs as sagemaker-user
        'root': 'sagemaker-studio-kernel',  # from notebook container, studio runs as root
    }

    return user_to_aws_jupyter_type.get(whoami)


def info_on():
    import logging
    from sys import stdout

    logging.basicConfig(stream=stdout, level=logging.INFO)


def info_off():
    import logging
    from sys import stdout

    logging.basicConfig(stream=stdout, level=logging.WARNING)

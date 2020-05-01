import setuptools

setuptools.setup(
    name='bugdex',
    packages=['bugdex'],
    install_requires=[
        'boto3', 'toolz', 'pynamodb', 'attrs',
        'more-itertools',
        'immutables',
        'jira',
        'pytz',  # time zones
        'requests',
        'mistletoe @ git+https://github.com/andrew-lee-zuora/mistletoe@importable-contrib',
        'zsec-aws-tools @ git+https://github.com/zuoralabs/zsec-aws-tools.git@v0.1.19'
    ],
    extras_require={'test': ['toolz', 'pytest']},
    scripts=['utils/split-jira-issue.py'],
    version='v0.1.15',
    classifiers=[
        'Programming Language :: Python :: 3.8',
    ]
)

"""
Based entirely on Django's own ``setup.py``.
"""
from setuptools import find_packages
from setuptools import setup

import ctags

setup(
    name='ctags',
    version=ctags.__version__,

    description='Canonical, localized tagging application for Django',
    long_description='\n'.join([open('README.md').read(),
                                open('CHANGELOG.txt').read()]),
    keywords='django, tag, tagging, canonical',

    author=ctags.__author__,
    author_email=ctags.__author_email__,
    maintainer=ctags.__maintainer__,
    maintainer_email=ctags.__maintainer_email__,
    url=ctags.__url__,
    license=ctags.__license__,

    packages=find_packages(),
    include_package_data=True,
    zip_safe=False,

    classifiers=[
        'Framework :: Django',
        'Environment :: Web Environment',
        'Operating System :: OS Independent',
        'Development Status :: 5 - Production/Stable',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: BSD License',
        'Programming Language :: Python',
        'Programming Language :: Python :: 3',
        'Topic :: Utilities',
        'Topic :: Software Development :: Libraries :: Python Modules']
)

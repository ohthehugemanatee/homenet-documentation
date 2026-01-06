#!/bin/bash

git clone https://gitlab.com/khassel/magicmirror-helm.git
helm upgrade magicmirror -i magicmirror-helm -f values.yaml

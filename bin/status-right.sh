#!/bin/bash

acpi -b | cut --delimiter=" " --fields=3-4 | sed -e 's/,//g'

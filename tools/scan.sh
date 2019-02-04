#!/bin/bash

echo {"t":"scan"} | ncat -u 255.255.255.255 7000

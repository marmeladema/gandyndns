# Gandyndns

## What is Gandyndns?
Gandidyndns is a dynamic IP updater based on Gandi API (>=3.3.36).
It can handle IPv4 and IPv6 although care should taken for IPv6 if you use dynamic/temporary addresses.

## How does it work?
Well, read the code, it's pretty simple :]
In short, it does the following for each domain that has to be updated:

1. Retrieve current address from http://whatip.me
2. Resolve current domain from google dns server
3. If both match than, everything is up to date! If not we go on.
4. Retrieve current zone version from gandi
5. If a record with the same name/type/value is found, then current zone version is up to date, but not propagated yet! If not we go on.
6. Create new zone version
7. Update or create a record for the current domain
8. Set current zone version to newly created version
Done.

## How to install it?
    python3 setup.py install

If you do not plan to share it among different users, you can (and maybe should) install it in your own user site-package directory with:

    python3 setup.py install --user

You can also install it in a virtualenv.

## How to use it?
### Basic configuration
    [test.example.com]
    apikey = d41d8cd98f00b204e9800998ecf8427e
    record_name = test
    record_type = A
    zone_id = 1337

You can find your **zone_id** from Gandi zone edition url:

    https://www.gandi.net/admin/domain/zone/<zone_id>/<zone_version>/edit

So for example, if you have to visit this url to edit your zone:

    https://www.gandi.net/admin/domain/zone/1337/12/edit

Then, your **zone_id** is **1337**

You can either have different config files or have multiple sections in the same config file, as you wish.

### Basic usage
    $ gandyndns /path/to/gandyndns.conf

Gandyndns does not need any priviledge besides internet access to run, so avoid running it as root.



Cheers

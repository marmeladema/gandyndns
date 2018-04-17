# Gandyndns

## What is Gandyndns?
Gandidyndns is a dynamic IP updater based on Gandi LiveAPI.
It can handle IPv4 and IPv6 although care should taken for IPv6 if you use dynamic/temporary addresses.

## How does it work?
Well, read the code, it's pretty simple :]
In short, it does the following for each domain that has to be updated:

1. Retrieve current address(es) from http://whatip.me
For each type of each record of each domain from the configuration:
2. Retrieve current record from gandi
3. If both records match, current record is up to date!
4. If not, we upgrade gandi with current record informations
Done.

## How to install it?
    python3 setup.py install

If you do not plan to share it among different users, you can (and maybe should) install it in your own user site-package directory with:

    python3 setup.py install --user

You can also install it in a virtualenv.

## How to use it?

Configuration file is written in json format.

### Basic configuration
    {
        "domains": {
            "example.com": {
                "apikey": "d41d8cd98f00b204e9800998ecf8427e",
                "records" : {
                    "test": {
                        "A": {
                            "rrset_values":["{remote_addr}"]
                        }
                    }
                }
            }
        }
    }

You can either have different config files or have multiple domains in the same config file, as you wish.

### Basic usage
    $ gandyndns /path/to/gandyndns.conf

Gandyndns does not need any priviledge besides internet access to run, so avoid running it as root.



Cheers

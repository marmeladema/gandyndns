import sys
import requests
import xmlrpc.client
import logging

whatip_url = {
	'remote_addr': 'http://ipv4.whatip.me/?json',
	'remote_addr6': 'http://ipv6.whatip.me/?json',
}

def gandyndns(domain, apikey, records, logging_level = None, logging_handler = None):
	logger = logging.getLogger('gandyndns')

	if logging_level:
		logger.setLevel(int(logging_level))
	else:
		logger.setLevel(logging.INFO)

	if not logging_handler:
		logging_handler = logging.StreamHandler(sys.stdout)

	logger.addHandler(logging_handler)

	logger.debug('Retrieving current addresses from whatip.me')
	params = {}
	for param in whatip_url:
		try:
			r = requests.get(url=whatip_url[param])
			address = r.json()['ip']
			logger.info('Current {{{}}} is: {}'.format(param, address))
			params[param] = address
		except:
			logger.warning('Could not retrieve {{{}}}'.format(param))

	api = requests.Session()
	api.headers.update({'X-Api-Key': apikey})
	api.headers.update({'Content-Type': 'application/json'})

	success = True

	for record_name in records:
		for record_type in records[record_name]:
			record = records[record_name][record_type]

			for i in range(len(record.get('rrset_values', []))):
				record['rrset_values'][i] = record['rrset_values'][i].format(**params)

			response = api.get('https://dns.api.gandi.net/api/v5/domains/{}/records/{}/{}'.format(domain, record_name, record_type))
			data = response.json()
			if response.status_code in [200, 404]:
				if data.get('rrset_values', []) == record.get('rrset_values', []):
					logger.info('Record {} of domain {} is up to date!'.format(repr(record_name), repr(domain)))
				else:
					data.update(record)
					response = api.put(
						'https://dns.api.gandi.net/api/v5/domains/{}/records/{}/{}'.format(domain, record_name, record_type),
						json = data,
					)
					data = response.json()

					if response.status_code in [200, 201]:
						logger.info('Record {} of domain {} has been updated: {}'.format(repr(record_name), repr(domain), data['message']))
					else:
						logger.error('Could not update record {} of domain {}: {}'.format(repr(record_name), repr(domain), data['errors']))
						success = False
			else:
				logger.error('Could not retrieve record {} of domain {}: {}'.format(repr(record_name), repr(domain), data))

	return success

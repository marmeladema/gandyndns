import sys
import requests
import xmlrpc.client
import dns.resolver
import logging

whatip_url = {
	'A': 'http://ipv4.whatip.me/?json',
	'AAAA': 'http://ipv6.whatip.me/?json',
}

def gandyndns(domain, apikey, zone_id, record_name = None, record_type = None, record_ttl = None, logging_level = None, logging_handler = None):
	zone_id = int(zone_id)

	record = {}
	if record_name:
		record['name'] = record_name
	else:
		record['name'] = domain+'.'
	if record_type:
		if record_type in ['A', 'AAAA']:
			record['type'] = record_type
		else:
			raise ArgumentError('[{}] record_type should be A or AAAA, not {}'.format(domain, record_type))
	else:
		record['type'] = 'A'
	if record_ttl:
		record['ttl'] = int(record_ttl)

	logger = logging.getLogger('gandyndns')

	if logging_level:
		logger.setLevel(int(logging_level))
	else:
		logger.setLevel(logging.INFO)

	if not logging_handler:
		logging_handler = logging.StreamHandler(sys.stdout)

	logger.addHandler(logging_handler)

	logger.debug('Retrieving current address from whatip.me')
	r = requests.get(url=whatip_url[record['type']])
	address = r.json()['ip']
	logger.info('Current address is: {}'.format(address))

	api = xmlrpc.client.ServerProxy('https://rpc.gandi.net/xmlrpc/')

	resolver = dns.resolver.Resolver()
	resolver.nameservers = ['8.8.8.8', '8.8.4.4']

	try:
		answers = resolver.query(domain, record['type'])
		for rdata in answers:
			record['value'] = str(rdata)
			if str(rdata) == address:
				logger.info('Domain {} with address {} is up to date!'.format(repr(domain), repr(address)))
				return True
	except:
		record['value'] = address
	logger.info('Domain {} is outdated!'.format(repr(domain)))

	logger.debug('Retrieving current zone records from gandi')
	zone_records = api.domain.zone.record.list(apikey, zone_id, 0)
	logger.debug('Current zone records are: {}'.format(zone_records))

	for zone_record in zone_records:
		if zone_record['name'] == record['name'] and zone_record['type'] == record['type'] and zone_record['value'] == record['value']:
			logger.info('Current zone version is already up to date!')
			return True
	logger.info('Current zone version is out of date!')

	logger.debug('Creating new zone version')
	zone_version = api.domain.zone.version.new(apikey, zone_id)
	logger.debug('New zone version is: {}'.format(zone_version))

	logger.debug('Retrieving list of zone records')
	zone_records = api.domain.zone.record.list(apikey, zone_id, zone_version)
	logger.debug('List of zone records is: {}'.format(zone_records))
	for zone_record in zone_records:
		if zone_record['name'] == record['name'] and zone_record['type'] == record['type']:
			if zone_record['value'] == record['value']:
				logger.info('Current zone record is already up to date!')
				return True
			zone_record.update(record)

	if 'id' in record:
		record_id = record.pop('id')
		logger.debug('Updating record: {}'.format(record))
		result = api.domain.zone.record.update(apikey, zone_id, zone_version, {'id': record_id}, record)
	else:
		logger.debug('Adding record: {}'.format(record))
		result = api.domain.zone.record.add(apikey, zone_id, zone_version, record)
	logger.debug('Record is now: {}'.format(result))

	logger.debug('Setting zone version to: {}'.format(zone_version))
	api.domain.zone.version.set(apikey, zone_id, zone_version)

import socket
import os.path
import enum
import argparse
import hashlib
from struct import pack, unpack, error as struerror
from io import BytesIO
from sys import exit


@enum.unique
class Options(enum.IntFlag):
	"""Communication options shared between Sender and Receiver

	Option values have to be powers of 2 up to 128
	"""
	SINGLE_FILE	= 1	# transfer of single file
	MULTI_FILES = 2	# transfer of multiple files
	TIMEOUT = 4		# use timeout of 'Transport.TIMEOUT' seconds
	NO_TIMEOUT = 16 # no timeout

class Transport:
	BUFFERSIZE = 4096
	TIMEOUT = 60.0

	def __init__(self, sock, address):
		if not sock:
			self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
			self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
		else:
			assert sock.family is socket.AF_INET and sock.type is socket.SOCK_STREAM, \
				"socket is of wrong type"
			self.sock = sock

		if address: self.sock.bind(address)

	@staticmethod
	def options_to_byte(*options):
		byte = 0
		for op in options:
			byte |= op.value
		return pack('>B', byte)

	@staticmethod
	def byte_to_options(byte):
		_byte = unpack('>B', byte)[0]
		options = []
		for i in range(8):
			if _byte & (1 << i):
				options.append(Options(1<<i))
		return options

	def send_data(self, stream, length):
		# assert stream.mode == 'rb', "stream has to be of 'rb' mode"
		sha = hashlib.sha256()
		totalsent = 0
		while totalsent < length:
			chunk = stream.read(BUFFERSIZE)
			sha.update(chunk)

			chunksent = 0
			while chunksent < len(chunk):
				sent = self.sock.send(chunk)
				if not sent:
					raise RuntimeError('connection broken')
				chunksent += sent
			totalsent += chunksent
		return sha.digest()

	def recv_data(self, stream, size):
		# assert stream.mode == 'wb', "stream has to be of 'wb' mode"
		sha = hashlib.sha256()
		bytesread = 0
		while bytesread < size:
			chunk = self.sock.recv(BUFFERSIZE)
			if not chunk:
				raise RuntimeError('connection broken')
			stream.write(chunk)
			sha.update(chunk)
			bytesread += len(chunk)
		return sha.digest()

	def send_ack(self):
		with BytesIO(b'\x01') as f:
			self.send_data(f, 1)

	def recv_ack(self):
		ack = self.sock.recv(1)
		# ack == b'\x01' ? True : False
		return True if ack == b'\x01' else False



class Sender(Transport):
	def __init__(self, *options, sock=None, address=None):
		super().__init__(sock, address)
		if options:
			self.options = list(set(options))
			assert all(isinstance(x, Options) for x in self.options)
			if Options['TIMEOUT'] in self.options: self.sock.settimeout(Transport.TIMEOUT)
		else:
			self.options = [Options['NO_TIMEOUT'], ] # default options
		# 

	def connect(self, peer):
		self.sock.connect(peer)

	def send_options(self):
		# maybe a bit overkill, as we're only sending 1 byte
		with BytesIO(self.options_to_byte(self.options)) as s:
			self.send_data(s, 1)

	def send_file_size(self, filename):
		length = os.path.getsize(filename)
		length_bytes = pack('>Q', length)
		with BytesIO(length_bytes) as f:
			self.send_data(f, 8)



class Receiver(Transport):
	def __init__(self, sock=None, address=None):
		super().__init__(sock, address)

	def listen(self):
		# check if socket already bound
		try:
			self.sock.getsockname()
		except OSError:
			self.sock.bind('', 0)
		self.sock.listen(3)

	def recv_options(self):
		try:
			self.options = self.byte_to_options(self.sock.recv(1))
		except struerror:
			return False
		return True




def read_args():
	parser = argparse.ArgumentParser(description='send or receive file/s')
	parser.add_argument('mode', choices=['send', 'recv'], 
		help='mode for sending or receiving')
	parser.add_argument('-lh', '--lhost', nargs=2, 
		help='address to bind to (host, port)')
	parser.add_argument('-rh', '--rhost', nargs=2, 
		help='address to connect to (REQUIRED with -s)')
	parser.add_argument('-f', '--file', nargs=argparse.REMAINDER, 
		help='file/s to be sent')

	options = parser.add_argument_group(title='options [only in send mode]')
	options.add_argument('--timeout', action='store_const', const=Options['TIMEOUT'], 
		default=Options['NO_TIMEOUT'], help='use %ssec timeout' % Transport.TIMEOUT)

	args = parser.parse_args()
	return args


def send(sender, files):
	assert all(os.path.isfile(x) for x in files), \
		"given paths for files must be existing files"
	sender.send_options()
	if not recv_ack():
		raise RuntimeError('ACK failed')
	for fn in files:
		sender.send_file_size(fn)

def recv(receiver):
	pass


def Main():
	args = read_args()
	if args.mode == 'send':
		if not args.file:
			exit("[!] atleast one file must be given in 'send' mode")
		if not args.rhost:
			exit("[!] remote address must be given in 'send' mode")
		if args.lhost:
			sender = Sender(
				Options['MULTI_FILES'] if len(args.file) > 1 else Options['SINGLE_FILE'], 
				args.timeout, address=(args.lhost[0], int(args.lhost[1])))
		else:
			sender = Sender(
				Options['MULTI_FILES'] if len(args.file) > 1 else Options['SINGLE_FILE'], 
				args.timeout)
		try:
			sender.connect((args.rhost[0], int(args.rhost[1])))
		except socket.error:
			exit('[!] failed to connect to remote host')
		try:
			send(sender, args.file)
		except socket.timeout:
			print('[!] socket timed out')
			raise
		# print(sender.sock)
		# print(sender.options)

	elif args.mode == 'recv':
		pass

if __name__ == '__main__':
	Main()




# s = Sender()
# s.a = 111
# z = Sender()
# print(z.a)


# byte = Transport.options_to_byte(Options.YES, Options.NO, Options.MAYBE) 
# print(byte)
# print(Transport.byte_to_options(byte))
import socket
import os.path
import enum
import argparse
import hashlib
from struct import pack, unpack, error as struerror
from io import BytesIO
from sys import exit


class FilenameTooLongError(Exception):
	pass



@enum.unique
class Options(enum.IntFlag):
	"""Communication options shared between Sender and Receiver.

	Option values have to be powers of 2 up to 128.
	"""
	SINGLE_FILE = 1	# transfer of single file
	MULTI_FILES = 2	# transfer of multiple files
	TIMEOUT = 4	# use timeout of 'Transport.TIMEOUT' seconds
	NO_TIMEOUT = 16	# no timeout



class Transport:
	"""Base class for Sender And Receiver.

	Contains core sending and receiving mechanisms.
	"""
	BUFFERSIZE = 16384
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
		""" Convert Options members to bits and pack into single byte."""
		byte = 0
		for op in options[0]:
			byte |= op.value
		return pack('>B', byte)

	@staticmethod
	def byte_to_options(byte):
		""" Convert single byte to list of Options members."""
		_byte = unpack('>B', byte)[0]
		options = []
		for i in range(8):
			if _byte & (1 << i):
				options.append(Options(1<<i))
		return options

	def send_data(self, stream, length):
		""" send_data(stream, length) -> hash of sent data as packed bytes 

		Send length amount of data in chunks of Transport.BUFFERSIZE from binary stream. 
		Raises RuntimeError if connection is broken.
		"""
		sha = hashlib.sha256()
		totalsent = 0
		while totalsent < length:
			chunk = stream.read(self.BUFFERSIZE)
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
		""" recv_data(stream, size) -> hash of received data as packed bytes 

		Receive size amount of data in chunks of Transport.BUFFERSIZE from binary stream. 
		Raises RuntimeError if connection is broken.
		"""
		sha = hashlib.sha256()
		bytesread = 0
		while bytesread < size:
			chunk = self.sock.recv(self.BUFFERSIZE)
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

	def send_hash(self, _hash):
		""" Send SHA256 hash as Bytes stream of 32 bytes."""
		with BytesIO(_hash) as f:
			self.send_data(f, 32)

	def recv_hash(self):
		""" Receive SHA256 hash as packed bytes."""
		with BytesIO() as _hash:
			self.recv_data(_hash, 32)
			_hash.seek(0)
			return _hash.read()



class Sender(Transport):
	""" Class responsible for sending files.

	Object of this class is used when in 'send' mode. 
	"""
	def __init__(self, *options, sock=None, address=None):
		super().__init__(sock, address)
		if options:
			self.options = list(set(options))
			assert all(isinstance(x, Options) for x in self.options)
			if Options['TIMEOUT'] in self.options: self.sock.settimeout(Transport.TIMEOUT)
		else:
			self.options = [Options['NO_TIMEOUT'], ] # default options

	def connect(self, peer):
		self.sock.connect(peer)

	def send_options(self):
		""" Send a list of Options members packed into a single byte."""
		# maybe a bit overkill, as we're only sending 1 byte
		with BytesIO(self.options_to_byte(self.options)) as s:
			self.send_data(s, 1)

	def send_file_size(self, filename):
		""" Send size of file with filename packed into big-endian 8 bytes."""
		length = os.path.getsize(filename)
		length_bytes = pack('>Q', length)
		with BytesIO(length_bytes) as f:
			self.send_data(f, 8)

	def send_filename(self, fn):
		""" Send filename padded to 255 bytes."""
		if len(fn) > 255:
			raise FilenameTooLongError('%s contains more than 255 characters' % fn)
		with BytesIO(bytes(fn.ljust(255, '\x00'), 'utf-8')) as f:
			self.send_data(f, 255)



class Receiver(Transport):
	""" Class responsible for receiving files.

	Object of this class is used when in 'recv' mode. 
	"""
	def __init__(self, sock=None, address=None):
		super().__init__(sock, address)
		self.s_sock = self.sock
		del self.sock

	def listen(self):
		""" call listen() on the underlying server socket.

		This also makes sure the socket is bound before calling listen().
		"""
		try:
			self.s_sock.getsockname() # check if socket already bound
		except OSError:
			self.s_sock.bind(('', 0))
		self.s_sock.listen(3)

	def recv_options(self):
		""" recv_options() -> True/False

		Receives a list of Options members as a packed byte, unpacks them to a 
		list and assigns to self.options.
		"""
		try:
			self.options = self.byte_to_options(self.sock.recv(1))
		except struerror:
			return False
		return True

	def recv_file_size(self):
		""" Receive size of file packed into big-endian 8 bytes and return it as integer.

		Returns 0 on unsuccessful unpack.
		"""
		try:
			with BytesIO() as s:
				self.recv_data(s, 8)
				s.seek(0)
				return unpack('>Q', s.read())[0]
		except RuntimeError:
			return 0

	def recv_filename(self):
		""" Receive padded filename, remove padding and return it as string. """
		with BytesIO() as fn:
			self.recv_data(fn, 255)
			fn.seek(0)
			return str(fn.read(), 'utf-8').rstrip('\x00')



def read_args():
	parser = argparse.ArgumentParser(description='send or receive file/s')
	parser.add_argument('mode', choices=['send', 'recv'], 
		help='mode for sending or receiving')
	parser.add_argument('-lh', '--lhost', nargs=2, 
		help='address to bind to (host, port)')
	parser.add_argument('-rh', '--rhost', nargs=2, 
		help='address to connect to (REQUIRED in send mode)')
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
	print('[*] Connected to: [%s:%s]' % sender.sock.getpeername())
	sender.send_options()
	if not sender.recv_ack():
		raise RuntimeError('ACK failed')

	for fn in files:
		sender.send_file_size(fn)
		if not sender.recv_ack():
			raise RuntimeError('ACK failed')
		sender.send_filename(fn)
		if not sender.recv_ack():
			raise RuntimeError('ACK failed')
		with open(fn, 'rb') as f:
			print('sending: %s ...' % fn)
			local_hash = sender.send_data(f, os.path.getsize(fn))
		if local_hash != sender.recv_hash():
			raise RuntimeError('Hash check failed')
		print('%s SENT' % fn)
		sender.send_ack()
	sender.sock.shutdown(socket.SHUT_WR) # end of communication


def recv(receiver):
	print('[*] Listening on: %s:%s' % receiver.s_sock.getsockname())
	receiver.sock, addr = receiver.s_sock.accept()
	print('[*] Connection from: [%s:%s]' % receiver.sock.getpeername())
	if not receiver.recv_options():
		raise RuntimeError('failed to unpack options byte')
	if Options['TIMEOUT'] in receiver.options: 
		receiver.sock.settimeout(Transport.TIMEOUT)
	receiver.send_ack()

	while True:
		length = receiver.recv_file_size()
		if not length:
			break
		receiver.send_ack()
		filename = receiver.recv_filename()
		receiver.send_ack()
		with open(filename, 'wb') as f:
			local_hash = receiver.recv_data(f, length)
		print('%s saved' % filename)
		receiver.send_hash(local_hash)
		if not receiver.recv_ack():
			raise RuntimeError('ACK failed')


def Main():
	args = read_args()
	transport = None
	try:
		if args.mode == 'send':
			if not args.file:
				exit("[!] atleast one file must be given in 'send' mode")
			if not args.rhost:
				exit("[!] remote address must be given in 'send' mode")
			if args.lhost:
				transport = Sender(
					Options['MULTI_FILES'] if len(args.file) > 1 else Options['SINGLE_FILE'], 
					args.timeout, address=(args.lhost[0], int(args.lhost[1])))
			else:
				transport = Sender(
					Options['MULTI_FILES'] if len(args.file) > 1 else Options['SINGLE_FILE'], 
					args.timeout)
			try:
				transport.connect((args.rhost[0], int(args.rhost[1])))
			except socket.error as e:
				print(e)
				exit('[!] failed to connect to remote host')
			send(transport, args.file)

		elif args.mode == 'recv':
			if args.lhost:
				transport = Receiver(address=(args.lhost[0], int(args.lhost[1])))
			else:
				transport = Receiver()
			transport.listen()
			recv(transport)
			
	except socket.timeout:
		print('[!] socket timed out')
	except FilenameTooLongError as e:
		print('[!] %s' % e)
	finally:
		# close sockets and alike
		if transport:
			transport.sock.close()
			if hasattr(transport, 's_sock'):
				transport.s_sock.close()



if __name__ == '__main__':
	Main()

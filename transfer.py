import socket
import os
import enum
from struct import pack, unpack


@enum.unique
class Options(enum.IntFlag):
	YES = 1
	NO = 8
	MAYBE = 64

class Transport:
	BUFFERSIZE = 4096

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

	def send_data(self, data, length):
		pass


class Sender(Transport):
	def __init__(self, *options, sock=None, address=None):
		super().__init__(sock, address)
		if options:
			self.options = list(set(options))
			assert all(isinstance(x, Options) for x in self.options)
		else:
			pass
			# self.options = # [] some default options
		# 

	def send_options(self):
		# pass
		self.sock.sendall(self.options_to_byte(self.options))





class Receiver:
	pass


# s = Sender()
# s.a = 111
# z = Sender()
# print(z.a)


# byte = Transform.options_to_byte(Options.YES, Options.NO, Options.MAYBE) 
# print(byte)
# print(Transform.byte_to_options(byte))
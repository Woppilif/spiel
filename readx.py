#!/usr/bin/env python3

import signal
import time
import sys
import os
import traceback
import json

#import requests
#from requests_toolbelt.utils import dump

import ndef
from pirc522 import RFID

#ToDo: rm if not needed
class NeedsResetException(Exception):
    def __init__(self, module):
        self.module = module
    pass

class RFIDWrapper:
    KEY = [0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF]
    def __init__(self):
        self._create()

    def wait_for_tag(self):
        self.rdr.wait_for_tag()

    def _prepare_request(self):
        """Returns (error, uid)"""
        try:
            (error, tag_type) = self.rdr.request()
            if error: return (error, None)
            (error, uid) = self.rdr.anticoll()
            if error: return (error, None)
            print("Found card UID: " + str(uid))
            return (self.rdr.select_tag(uid), uid)
        except:
            self.rdr.stop_crypto()

    def read_ndef_bytes(self):
        """Returns bytes or raises exception"""
        def get_length(block):
            if block[4] == bytes([0]):
                raise Exception("ndef record longer than 256 bytes. Please implement =)")
            else:
                return block[4]
        
        def read_block(block_address):
            (error, read) = self.rdr.read(block_address)
            
            if error: 
                print('READ B {0}'.format(error))
                raise Exception("failed to read block %s" % block_address)
            else:
                return bytes(read)

        try:
            (error, uid) = self._prepare_request()
            print('PREP B {0}'.format(error))
            if error: raise Exception("failed to prepare request")

            error = self.rdr.card_auth(self.rdr.auth_b, 4, self.KEY, uid)
            print('AUTH {0}'.format(error))
            if error: raise Exception("failed to auth sector 1")
            
            start_block = 4
            read = read_block(start_block)
            # ndef records starts with this sequence:
            print("#########################")
            print(str(read))

            if read[:3] != bytes([0, 0, 3]):
                raise Exception("Start block with invalid starting sequence: %s" % read)
            length = get_length(read)
            bytes_to_read = length
            print("Found NDEF with %s length" % length)
            ndef_bytes = read[4:(4+bytes_to_read)]
            bytes_to_read -= 16-4
            for i in range(start_block+1, 63):
                if bytes_to_read <= 0:
                    break
                elif i % 4 == 3:
                    #ignore every 4th blocks (reserved for key mgmt), but auth for next sector
                    error = self.rdr.card_auth(self.rdr.auth_b, i+1, self.KEY, uid)
                    if error: raise Exception("failed to auth sector %s" % i/4)
                    continue
                else:
                    ndef_bytes += read_block(i)[:bytes_to_read]
                    bytes_to_read -= 16
            print("found ndef bytes: %s" % str(ndef_bytes))
            if length != len(ndef_bytes):
                self._recreate()
                raise Exception("Could not read all NDEF bytes (Declared: %i, got: %i)" % (length, len(ndef_bytes)))
            return ndef_bytes
        finally:
            self.rdr.stop_crypto()

    def write_ndef(self, record_bytes):
        def zpad(list, count):
            """padds with zeros to the end"""
            return (list + bytes(count))[:count]

        block_address = 4
        length = len(record_bytes)
        octets = bytes([0, 0, 3, length]) + record_bytes + b'\xFE'

        print("Want to write %s" % octets)

        try:
            (error, uid) = self._prepare_request()
            if error: raise Exception("failed to prepare request")

            error = self.rdr.card_auth(self.rdr.auth_b, block_address, self.KEY, uid)
            if error: raise Exception("failed to auth sector 1")

            while len(octets) > 0:
                if block_address % 4 == 3:
                    #do auth for next sector
                    error = self.rdr.card_auth(self.rdr.auth_b, block_address+1, self.KEY, uid)
                    if error: raise Exception("failed to auth block %s" % block_address+1)
                else:
                    block = zpad(octets, 16)
                    print("writing on block %i: %s" % (block_address, block))
                    if self.rdr.write(block_address, block):
                        raise Exception("failed to write on %s: %s" % (block_address, block))
                    octets = octets[16:]
                block_address += 1
        finally:
            self.rdr.stop_crypto()

    def _create(self):
        self.rdr = RFID()
        self.util = self.rdr.util()
        self.util.debug = True
        self.util.auth(self.rdr.auth_b, [0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF])

    #todo: check if needed (_prepare before each request should do the trick)
    def _recreate(self):
        self._reset()
        self._create()

    def _reset(self):
        self.util.deauth()
        self.rdr.cleanup()



        

def end_read(signal, frame):
    print("\nCtrl+C captured, ending read.")
    #cleanup()

def silently(lam):
    try:
        lam("")
    except BaseException as e:
        print("Got silenced Exception: "+e)


def cleanup():
    #silently(lambda _:sp.pause_playback(device_id))
    global run
    run = False
    silently(lambda _:wrapper._reset())
    sys.exit()

# todo: read once

#todo: rm, use request
def is_tag_present():
    rdr = wrapper.rdr
    rdr.init()
    rdr.irq.clear()
    rdr.dev_write(0x04, 0x00)
    rdr.dev_write(0x02, 0xA0)

    rdr.dev_write(0x09, 0x26)
    rdr.dev_write(0x01, 0x0C)
    rdr.dev_write(0x0D, 0x87)
    present = rdr.irq.wait(0.1)
    rdr.irq.clear()
    rdr.init()
    return present
'''
def spotify_client():
    scope = 'user-modify-playback-state,user-read-playback-state'
    username = os.environ['USERNAME']
    client_id = os.environ['CLIENT_ID']
    client_secret = os.environ['CLIENT_SECRET']
    token = spotipy_util.prompt_for_user_token(username, scope, client_id, client_secret, "http://google.de", "/home/pi/.cache-mattelacchiato")
    print("Acquired token: %s" % token)

    if not token:
        raise Exception("can't get token for " + username)
    return spotipy.Spotify(auth=token)
'''   

def parse_records(octets):
    records = list(ndef.message_decoder(octets))
    if records[0].type != "urn:nfc:wkt:U":
        raise Exception("Only URI records are supported. Was: "+str(records[0]))
    elif not records[0].uri.startswith("https://open.spotify.com"):
        raise Exception("Currently, only spotify links are supported. Was: "+str(records[0]))
    else:
        return records


def prepareOnce():
    signal.signal(signal.SIGINT, end_read)
    print("Starting")
    global sp, device_id, run
    
    run = True
    sp = None
    '''
    device_id = os.environ["DEVICE_ID"]
    while sp == None:
        try:
            sp = spotify_client()
        except BaseException:
            traceback.print_exc(file=sys.stdout)
            time.sleep(2)
    '''


try:
    prepareOnce()
    wrapper = RFIDWrapper()
    while run:
        print("Running")

        try:
            print("Wait for tag")
            wrapper.wait_for_tag()

            ndef_bytes = wrapper.read_ndef_bytes()
            records = parse_records(ndef_bytes)
            print(records[0].uri)
            offset = {"uri": records[1].uri} if len(records) > 1 else None
            #sp.start_playback(device_id=device_id, context_uri=records[0].uri, offset=offset)
            while is_tag_present():
                print("Tag is present")
                '''
                try:
                    time.sleep(1)
                    currently_playing = sp.currently_playing()
                    current_track = currently_playing["item"]["uri"]
                    print("current track: "+str(current_track))
                    current_track_rec = ndef.UriRecord(current_track)
                    if len(records) < 2:
                        print("appending.")
                        records.append(current_track_rec)
                        record_bytes = b''.join((ndef.message_encoder(records)))
                        wrapper.write_ndef(record_bytes)
                    elif current_track != records[1].uri:
                        print("replacing " + str(records[1].uri))
                        records[1] = current_track_rec
                        record_bytes = b''.join((ndef.message_encoder(records)))
                        wrapper.write_ndef(record_bytes)
                except BaseException as e:
                    # non-fatal here. simply print for debugging
                    traceback.print_exc(file=sys.stdout)
                '''
            print("Tag removed")
            #sp.pause_playback(device_id)
            time.sleep(1)
        except BaseException as e:
            print("Ignoring Exception")
            traceback.print_exc(file=sys.stdout)
        finally:
            wrapper._recreate()
except BaseException as e:
    traceback.print_exc(file=sys.stdout)
finally:
    print("STOP")
    cleanup()

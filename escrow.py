import praw
import dogecoinrpc
from dogecoinrpc.exceptions import InsufficientFunds
import hashlib
import time
import os
import sys
import shutil
import logging
import logging.config

logging.basicConfig()

logging.config.fileConfig('log-config.ini')
LOG = logging.getLogger('dogeescrowbot')

### PLEASE SET THESE VALUES #####################

BOT_OWNER = ''
BOT_USERNAME = ''
BOT_PASSWORD = ''
BOT_VERSION = '0.1'

TIP_ADDRESS = ''
WALLET_PASSWORD = ''

MIN_DOGE_AMOUNT = 10
MAX_DOGE_AMOUNT = 10000

#################################################

HORIZONTAL_LINE = '***'
MIN_DOGE_AMOUNT_STRING = str(MIN_DOGE_AMOUNT)
MAX_DOGE_AMOUNT_STRING = str(MAX_DOGE_AMOUNT)

class Transaction():
    def __init__(self, message):
        self.logger = logging.getLogger(__name__)
        self.message = message
        self.dogeSeller = None
        self.dogeAmount = None
        self.dogeBuyer = None
        self.payment = None
        self.dogeBuyerAddress = None
        self.transactionCreationTime = None
        self.transactionID = None
        self.status = None
        self.transactionLocked = False
        self.sellerAccept = 'No'
        self.buyerAccept = 'No'
        self.escrowAddress = None
        self.waitingForDoge = False


    def parseTransaction(self):
        # Message should be in the following format:

        # User Selling Doge: /u/username
        # Amount Of Doge Being Sold: D500
        # User Buying Doge: /u/username
        # Goods/Money Being Used To Pay: $5 USD

        try:
            lines = self.message.body.split('\n')
            self.dogeSeller = self._getDogeSeller(lines[0])
            self.dogeBuyer = self._getDogeBuyer(lines[1])
            self.dogeAmount = self._getDogeAmount(lines[2])
            self.payment = self._getPayment(lines[3])
        except:
            self.logger.debug('Error parsing the following escrow request: ' +
                self.message.body)
            self.message.reply('There was an error while parsing your request. \
                This may have happened if you modified the fields before the \
                colon (:) in the request. Please try again by starting a new \
                request. If you believe you sent a correct request and there is \
                a bug, please contact /u/' + BOT_OWNER)
            return -1

        # Make sure that the author of the request is either the buyer or seller
        if((self.message.author.name.lower() != self.dogeSeller.lower()) and
           (self.message.author.name.lower() != self.dogeBuyer.lower())):
            self.logger.debug('Error starting escrow. The author (' +
                self.message.author.name + ') is neither the dogeSeller (' +
                self.dogeSeller + ') or the the dogeBuyer (' + self.dogeBuyer)
            self.message.reply('You must be either the buyer or seller \
                to initiate an escrow transaction')
            return -1

        # Make sure that the buyer and seller are different
        if(self.dogeSeller.lower() == self.dogeBuyer.lower()):
            self.logger.debug('Error starting escrow. The buyer (' +
                self.dogeBuyer + ') cannot be the same as the seller (' +
                self.dogeSeller + ')')
            self.message.reply('Why would you want to escrow with yourself? That\'s just silly!')
            return -1

        # Make sure the dogeAmount is an int
        if not self.__isInt(self.dogeAmount):
            self.logger.debug('The dogeAmount (' + self.dogeAmount + ') is not \
                an integer')
            self.message.reply('The amount of doge you entered (D' +
                self.dogeAmount + ') is invalid. For the time being, \
                please make sure the doge amount is in the following \
                format "D12345". Don\'t us any commas, periods, or letters \
                (such as "k").\n\nAlso note that for right now the minimum \
                doge that can be traded is D' + MIN_DOGE_AMOUNT_STRING + ' and the \
                maximum doge that can be traded is D' + MAX_DOGE_AMOUNT_STRING)
            return -1

        # Make sure the dogeAmount is between MIN_DOGE_AMOUNT and MAX_DOGE_AMOUNT
        if((int(self.dogeAmount) < MIN_DOGE_AMOUNT) or
           (int(self.dogeAmount) > MAX_DOGE_AMOUNT)):
            self.logger.debug('The dogeAmount entered (' + self.dogeAmount + ') is \
                not between the minimum (' + MIN_DOGE_AMOUNT_STRING + ') and the \
                maximum (' + MAX_DOGE_AMOUNT_STRING + ')')
            self.message.reply('The amount of doge you entered (' +
                self.dogeAmount + ') is not acceptable at this time. Please \
                make sure the doge amount is between ' + MIN_DOGE_AMOUNT_STRING +
                ' and ' + MAX_DOGE_AMOUNT_STRING)

            return -1

        self.transactionCreationTime = self.message.created_utc

        self.transactionID = hashlib.sha256(self.message.body + str(self.transactionCreationTime)).hexdigest()

        sellerAcceptLink = 'http://www.reddit.com/message/compose/?to=dogeescrowbot&subject=%2Baccept_escrow&message=' + self.transactionID
        buyerAcceptLink = 'http://www.reddit.com/message/compose/?to=dogeescrowbot&subject=%2Baccept_escrow&message=' + self.transactionID + '%0A%0APlease%20enter%20your%20receving%20address%20here:%20Dxxxxxxxxx'
        declineLink = 'http://www.reddit.com/message/compose/?to=dogeescrowbot&subject=%2Bdecline_escrow&message=' + self.transactionID
        statusLink = 'http://www.reddit.com/message/compose/?to=dogeescrowbot&subject=%2Bstatus&message=' + self.transactionID

        messageHeader = 'A new escrow transaction has been proposed. Please see below for the details.'
        sellerMessageFooterAccept = 'To accept this escrow transaction, please send an accept message: [[ACCEPT]](' + sellerAcceptLink + ')'
        buyerMessageFooterAccept = 'To accept this escrow transaction, please send an accept message: [[ACCEPT]](' + buyerAcceptLink + ')'
        messageFooterDecline = 'To decline this escrow transaction, please send a decline message: [[DECLINE]](' + declineLink + ')'
        messageFooterStatus = 'To check the status of this escrow transaction, please send a status message [[STATUS]](' + statusLink + ')'

        sellerMessageBody = '\n\n'.join([messageHeader, '>' + lines[0], '>' + lines[1], '>' + lines[2], '>' + lines[3], '>TransactionID: ' + self.transactionID, HORIZONTAL_LINE, sellerMessageFooterAccept, messageFooterDecline, messageFooterStatus])
        buyerMessageBody = '\n\n'.join([messageHeader, '>' + lines[0], '>' + lines[1], '>' + lines[2], '>' + lines[3], '>TransactionID: ' + self.transactionID, HORIZONTAL_LINE, buyerMessageFooterAccept, messageFooterDecline, messageFooterStatus])

        messages = {
            "sellerMessage" : sellerMessageBody,
            "buyerMessage" : buyerMessageBody
        }

        return messages

    def _getDogeSeller(self, line):
        # Make sure this line has the string "User Selling Doge: /u/"
        if(line.find('User Selling Doge: /u/') > -1):
            seller = line.split('/u/')[1]
        else:
            # If the line isn't correct, raise a parse error
            raise ParseError
        return seller

    def _getDogeBuyer(self, line):
        # Make sure this line has the string "User Buying Doge: /u/"
        if(line.find('User Buying Doge: /u/') > -1):
            buyer = line.split('/u/')[1]
        else:
            # If the line isn't correct, raise a parse error
            raise ParseError
        return buyer

    def _getDogeAmount(self, line):
        # Make sure this line has the string "Amount Of Doge Being Sold: D"
        if(line.find('Amount Of Doge Being Sold: D') > -1):
            amount = line.split(': D')[1]
        else:
            # If the line isn't correct, raise a parse error
            raise ParseError
        return amount

    def _getPayment(self, line):
        # Make sure this line has the string "In Return For:"
        if(line.find('In Return For:') > -1):
            payment = line.split(':')[1]
            # Strip the leading space if it was left in
            if(payment[0] == ' '):
                payment = payment[1:]
        else:
            # If the line isn't correct, raise a parse error
            raise ParseError
        return payment

    def __isInt(self, string):
        try:
            int(string)
            return True
        except ValueError:
            return False



class EscrowBot():
    def __init__(self):
        self.username = BOT_USERNAME
        self.password = BOT_PASSWORD
        self.user_agent = BOT_USERNAME + ' ' + BOT_VERSION + ' by /u/' + BOT_OWNER
        self.botOwner = BOT_OWNER
        self.dogecoinPassword = WALLET_PASSWORD
        self.ownerTipAddress = TIP_ADDRESS
        self.logger = logging.getLogger(__name__)
        self.rConn = None
        self.dConn = None
        self.running = None
        self.transactions = []
        self.passphraseDict = {}
        self.currentTransactionsDirectory = 'currentTransactions/'
        self.completedTransactionsDirectory = 'completedTransactions/'
        self.declinedTransactionsDirectory = 'declinedTransactions/'

    def connectToDogecoinWallet(self):
        self.logger.info('connecting to the local dogecoin wallet')
        conn = dogecoinrpc.connect_to_local()
        return conn

    def connectToReddit(self):
        self.logger.info('connecting to reddit')
        conn = praw.Reddit(user_agent=self.user_agent)
        conn.login(self.username, self.password)
        return conn

    def loadPassphraseDict(self):
        fileDict = {}
        with open('passphrase.txt') as passFile:
            for line in passFile:
                (key, value) = line.rstrip().split(':')
                fileDict[key] = value
        return fileDict

    def savePassphraseDict(self):
        with open('passphrase.txt', 'w') as passFile:
            for key in self.passphraseDict:
                try:
                    # This could fail if someone puts in some non-ascii phrase
                    passFile.write(key + ':' + self.passphraseDict[key] + '\n')
                except:
                    pass

    def start(self):
        self.rConn = self.connectToReddit()
        self.dConn = self.connectToDogecoinWallet()
        self.passphraseDict = self.loadPassphraseDict()

        # Begin Service
        try:
            # Go!
            self.running = True
            while(True):
                # Get Messages
                newMessages = self.getNewMessages()
                self.handleMessages(newMessages)
                time.sleep(2)
                for transaction in self.transactions:
                    # If we are waiting for doge, see if it has arrived
                    if(transaction.waitingForDoge):
                        # See how much has been sent to the address
                        amountPaid = int(self.dConn.getreceivedbyaddress(transaction.escrowAddress))
                        if(amountPaid >= int(transaction.dogeAmount)):
                            # Get the dogechain transaction link
                            txid = self.dConn.listtransactions(account=transaction.transactionID)[0].txid
                            dogechainURL = "http://www.dogechain.info/tx/" + txid

                            # Send message to both buyer and seller
                            subject = 'Doge Deposited in Escrow Account'

                            dogeBuyerMessage = '/u/' + transaction.dogeSeller + ' has deposited [' + transaction.dogeAmount + '] doge into ' + transaction.escrowAddress + '\n\nHere\'s a link to the transaction: [[Dogechain Link]](' + dogechainURL + ')\n\nPlease send the payment [' + transaction.payment + '] to /u/' + transaction.dogeSeller

                            releaseFundsLink = 'http://www.reddit.com/message/compose/?to=dogeescrowbot&subject=%2Brelease_funds&message=' + transaction.transactionID
                            dogeSellerMessage = '/u/' + transaction.dogeSeller + ' has deposited [' + transaction.dogeAmount + '] doge into ' + transaction.escrowAddress + '\n\nHere\'s a link to the transaction: [[Dogechain Link]](' + dogechainURL + ')\n\n/u/' + transaction.dogeBuyer + ' has been informed and should be sending the payment [' + transaction.payment + '] shortly.\n\nOnce the payment has arrived, please send the message to release the funds [[RELEASE FUNDS]](' + releaseFundsLink + ')'

                            self.logOutgoingTransactionMessage(transaction, transaction.dogeBuyer, subject, dogeBuyerMessage)
                            self.logOutgoingTransactionMessage(transaction, transaction.dogeSeller, subject, dogeSellerMessage)

                            self.sendMessage(transaction.dogeBuyer,
                                subject,
                                dogeBuyerMessage)
                            self.sendMessage(transaction.dogeSeller,
                                subject,
                                dogeSellerMessage)
                            # Stop checking to see if the doge was deposited
                            transaction.waitingForDoge = False
        except KeyboardInterrupt:
            self.logger.info('Control-C was pressed')
            self.running = False

    def getNewMessages(self):
        messages = [m for m in self.rConn.get_unread()]
        return messages

    def handleMessages(self, messages):
        for message in messages:
            if(message.subject == '+help'):
                self.respondToHelpRequest(message)
            if(message.subject == '+register'):
                self.respondToRegisterRequest(message)
            if(message.subject == '+new_escrow'):
                self.respondToNewEscrowRequest(message)
            if(message.subject == '+status'):
                self.respondToStatusRequest(message)
            if(message.subject == '+accept_escrow'):
                self.respondToAcceptRequest(message)
            if(message.subject == '+decline_escrow'):
                self.respondToDeclineRequest(message)
            if(message.subject == '+release_funds'):
                self.respondToReleaseFunds(message)
            if(message.subject == '+dispute'):
                self.respondToDispute(message)

    def respondToHelpRequest(self, message):
        self._logHandleRequest('+help')
        message.mark_as_read()

        response = ''

        messageHeader = 'Hi /u/' + message.author.name + '!'
        response += messageHeader + '\n\n'

        # Determine number of active transactions for the sender
        messageTransactions = 'Here are your active transactions:\n\n'
        for transaction in self.transactions:
            if((transaction.dogeSeller.lower() == message.author.name.lower()) or (transaction.dogeBuyer.lower() == message.author.name.lower())):
                statusLink = 'http://www.reddit.com/message/compose/?to=dogeescrowbot&subject=%2Bstatus&message=' + transaction.transactionID
                messageTransactions += HORIZONTAL_LINE + '\n\n' \
                                        '>Doge Seller: /u/' + transaction.dogeSeller + '\n\n' \
                                        '>Doge Buyer: /u/' + transaction.dogeBuyer + '\n\n' \
                                        '>[[GET STATUS]](' + statusLink + ') ' + transaction.transactionID + '\n\n'
        messageTransactions += HORIZONTAL_LINE + '\n\n'
        response += messageTransactions

        newEscrowLink = 'http://www.reddit.com/message/compose/?to=dogeescrowbot&subject=%2Bnew_escrow&message=User%20Selling%20Doge:%20/u/username%0AUser%20Buying%20Doge:%20/u/username%0AAmount%20Of%20Doge%20Being%20Sold:%20D500%0AIn%20Return%20For:%20$5%20USD'
        newEscrowMessage = 'If you would like to start a new escrow trade, please click here: [[New Escrow]](' + newEscrowLink + ')\n\n'

        disputeLink = 'http://www.reddit.com/message/compose/?to=dogeescrowbot&subject=%2Bdispute&message=Transaction%20ID:%20%0APlease%20describe%20in%20detail%20the%20problem%20that%20occurred:%20'
        disputeMessage = 'To file a dispute, please click here: [[Dispute]](' + disputeLink + ')\n\n'

        response += newEscrowMessage
        response += disputeMessage

        self.replyToMessage(message, response)

    def respondToRegisterRequest(self, message):
        self._logHandleRequest('+register')
        message.mark_as_read()

        # Get the passphrase
        if('Passphrase:' not in message.body):
            self.replyToMessage(message, 'You modified the message is a way that removed the text "Passphrase:". You shouldn\'t do that. You should feel ashamed.')
            return
        passphrase = message.body.split('Passphrase:')[1]

        # Strip the leading space if it was left in
        if(passphrase[0] == ' '):
            passphrase = passphrase[1:]

        # Strip the [ and ] if the user kept them in the message
        if((passphrase[0] == '[') and
           (passphrase[-1] == ']')):
            passphrase = passphrase[1:-1]

        # Add the user (or update if they were already in the file)
        self.passphraseDict[message.author.name] = passphrase

        # Save the file
        self.savePassphraseDict()

        # Since savePassphrase could fail, we should reload passphraseDict
        self.passphraseDict = self.loadPassphraseDict()

        # See if the user got saved in the file
        if(message.author.name in self.passphraseDict):
            response = ''
            response += 'Thank you for registering! In the future, all messages \
            sent to you by this bot will begin with the same header as this message. \
            If you receive a message that doesn\'t have this header, it is almost \
            certainly someone trying to impersonate this bot. If the message did come \
            from this bot without the header please let /u/' + self.botOwner + ' know \
            so the bug can be fixed. Thanks!'

            self.replyToMessage(message, response)
        else:
            self.replyToMessage(message, 'Sorry! The passphrase you chose [' + passphrase + '] cannot be used. Please choose something else.')

    def respondToDispute(self, message):
        self._logHandleRequest('+dispute')
        message.mark_as_read()

        # Send message to owner
        self.sendMessage(self.botOwner, 'DogeEscrowBot Dispute From /u/' + message.author.name, message.body)

        # Let the user know a dispute message was sent
        self.replyToMessage(message, 'A dispute message has been sent to the owner (/u/' + self.botOwner + '). Please allow some time for the owner to contact you and review the case')

    def respondToNewEscrowRequest(self, message):
        self._logHandleRequest('+new_escrow')
        message.mark_as_read()

        # Create transaction object
        transaction = Transaction(message)
        responses = transaction.parseTransaction()

        # Make sure the response was not an invalid request
        if(responses is -1):
            # If this is the case, the response message was already sent to the user
            pass
        else:
            # Send response to the buyer and seller
            try:
                # Catch if someone tries to send to a non-user
                # Append the transaction
                self.transactions.append(transaction)
                # Create the transaction log
                self.createTransactionLog(transaction)
                # Send Message
                self.sendMessage(transaction.dogeSeller,
                    'Escrow Transaction Details',
                    responses['sellerMessage'])
                self.sendMessage(transaction.dogeBuyer,
                    'Escrow Transaction Details',
                    responses['buyerMessage'])

            except:
                self.replyToMessage(message, 'Sorry! The user you are attempting to trade with doesn\'t exist. Removing the following transaction: ' + transaction.transactionID)
                self.removeTransactionFile(transaction.transactionID)
                self.transactions.remove(transaction)

    def respondToStatusRequest(self, message):
        self._logHandleRequest('+status')
        message.mark_as_read()
        # Get the correct transaction given the ID
        transaction = self.getTransaction(message)
        if(transaction is None):
            self.replyToInvalidTransactionID(message)
        else:
            response = self.createStatusMessage(transaction)
            self.replyToMessage(message, response)

    def createStatusMessage(self, transaction):
        response = 'Transaction: ' + transaction.transactionID + '\n\n' + HORIZONTAL_LINE + '\n\n'
        response += 'Doge Seller: ' + transaction.dogeSeller + '\n\n' + 'Has seller accepted transaction? ' + transaction.sellerAccept + '\n\n'
        response += 'Doge Buyer: ' + transaction.dogeBuyer + '\n\n' + 'Has buyer accepted transaction? ' + transaction.buyerAccept + '\n\n'
        return response

    def respondToAcceptRequest(self, message):
        self._logHandleRequest('+accept_escrow')
        message.mark_as_read()
        # Get the correct transaction given the ID
        transaction = self.getTransaction(message)
        if(transaction is None):
            self.replyToInvalidTransactionID(message)
        else:
            # Log the message to the transaction log
            try:
                self.logIncomingTransactionMessage(transaction, message)
            except:
                self.logger.info('failed to log +accept_escrow message')
                self.replyToMessage(message, 'Sorry, there was a problem logging your message. This was most likely caused by using non-ascii characters. Please try again.')
                return

            # Is it the seller accepting?
            if(transaction.dogeSeller.lower() == message.author.name.lower()):
                transaction.sellerAccept = 'Yes'

            # Or is it the buyer?
            elif(transaction.dogeBuyer.lower() == message.author.name.lower()):
                # Get the buyer's address
                address = message.body.split(': ')[1]
                # Make sure it's a valid address
                if(self.dConn.validateaddress(address).isvalid):
                    transaction.dogeBuyerAddress = address
                    transaction.buyerAccept = 'Yes'
                else:
                    # Let the user know they sent a bad address
                    buyerAcceptLink = 'http://www.reddit.com/message/compose/?to=dogeescrowbot&subject=%2Baccept_escrow&message=' + transaction.transactionID + '%0A%0APlease%20enter%20your%20receving%20address%20here:%20Dxxxxxxxxx'
                    self.replyToMessage(message, 'Sorry, the address you entered [' + address + '] is not valid. Please accept again with a valid address. [[ACCEPT]](' + buyerAcceptLink + ')')

            # Have both parties accepted?
            if((transaction.sellerAccept == 'Yes') and (transaction.buyerAccept == 'Yes')):
                # Lock Transaction
                transaction.transactionLocked = True

                # Create escrow address
                transaction.escrowAddress = self.dConn.getnewaddress(account=transaction.transactionID)

                subject = 'Escrow Transaction Accepted'
                dogeSellerMessage = 'Transaction [' + transaction.transactionID + '] was accepted by both parties\n\nPlease send [' + transaction.dogeAmount + '] doge to the following escrow address: ' + transaction.escrowAddress
                dogeBuyerMessage = 'Transaction [' + transaction.transactionID + '] was accepted by both parties\n\nThe other party is sending [' + transaction.dogeAmount + '] doge to the following address: ' + transaction.escrowAddress + '\n\nYou will be notified when the doge has arrived'

                self.logOutgoingTransactionMessage(transaction, transaction.dogeSeller, subject, dogeSellerMessage)
                self.logOutgoingTransactionMessage(transaction, transaction.dogeBuyer, subject, dogeBuyerMessage)

                # Send message to dogeSeller letting them know to send the doge to the escrow address
                self.sendMessage(transaction.dogeSeller, subject, dogeSellerMessage)

                # Send message to dogeBuyer letting them know that the doge is being sent to the escrow address
                self.sendMessage(transaction.dogeBuyer, subject, dogeBuyerMessage)

                # Set 'waitingForDoge' flag
                transaction.waitingForDoge = True

            else:
                response = self.createStatusMessage(transaction)
                self.replyToMessage(message, response)

    def respondToDeclineRequest(self, message):
        self._logHandleRequest('+decline_escrow')
        message.mark_as_read()
        # Get the correct transaction given the ID
        transaction = self.getTransaction(message)
        if(transaction is None):
            self.replyToInvalidTransactionID(message)
        else:
            # Log the message to the transaction log
            try:
                self.logIncomingTransactionMessage(transaction, message)
            except:
                self.logger.info('failed to log +decline_escrow message')
                self.replyToMessage(message, 'Sorry, there was a problem logging your message. This was most likely caused by using non-ascii characters. Please try again.')
                return

            # Is someone declining?
            if((transaction.dogeSeller.lower() == message.author.name.lower()) or
               (transaction.dogeBuyer.lower() == message.author.name.lower())):
                # If the transaction is locked, let the user know they can't decline
                if(transaction.transactionLocked):
                    response = self.createUnableToDeclineMessage(transaction)
                    self.replyToMessage(message, response)
                # If the transaction hasn't been locked, let the user decline it
                else:
                    subject = 'Escrow Transaction Declined'
                    response = self.createDeclineMessage(message.author.name, transaction)

                    self.logOutgoingTransactionMessage(transaction, transaction.dogeBuyer, subject, response)
                    self.logOutgoingTransactionMessage(transaction, transaction.dogeSeller, subject, response)

                    self.sendMessage(transaction.dogeBuyer, subject, response)
                    self.sendMessage(transaction.dogeSeller, subject, response)

                    self.transactions.remove(transaction)
                    self.moveTransactionToDeclinedFolder(transaction.transactionID)

    def createDeclineMessage(self, decliner, transaction):
        response = '/u/' + decliner + ' has declined the escrow request \
            with transaction ID ' + transaction.transactionID + '.\n\nThis \
            transaction will no longer be active.'
        return response

    def createUnableToDeclineMessage(self, transaction):
        response = 'Sorry. Both parties have accepted the transaction [' + transaction.transactionID + '] and it cannot be declined.'
        return response

    def respondToReleaseFunds(self, message):
        self._logHandleRequest('+release_funds')
        message.mark_as_read()
        # Get the correct transaction given the ID
        transaction = self.getTransaction(message)
        if(transaction is None):
            self.replyToInvalidTransactionID(message)
        else:
            # Log the message to the transaction log
            try:
                self.logIncomingTransactionMessage(transaction, message)
            except:
                self.logger.info('failed to log +release_funds message')
                self.replyToMessage(message, 'Sorry, there was a problem logging your message. This was most likely caused by using non-ascii characters. Please try again.')
                return

            # Make sure the seller is sending the message
            if(transaction.dogeSeller.lower() == message.author.name.lower()):
                # Send to the buyer's address
                self.dConn.walletpassphrase(self.dogecoinPassword, 5)
                txid = self.dConn.sendtoaddress(transaction.dogeBuyerAddress, int(transaction.dogeAmount))
                dogechainURL = "http://www.dogechain.info/tx/" + txid

                # Let both the users know the transaction was completed
                response = '[' + transaction.dogeAmount + '] doge was transfered to the buyer\'s address!\n\nHere\'s a link to the transaction: [[Dogechain Link]](' + dogechainURL + ')\n\nIf you would like to support this bot, feel free to tip here: ' + self.ownerTipAddress + '\n\nThanks!'
                subject = 'Escrow Completed Successfully'

                self.logOutgoingTransactionMessage(transaction, transaction.dogeBuyer, subject, response)
                self.logOutgoingTransactionMessage(transaction, transaction.dogeSeller, subject, response)

                self.sendMessage(transaction.dogeBuyer, subject, response)
                self.sendMessage(transaction.dogeSeller, subject, response)

                self.moveTransactionToCompletedFolder(transaction.transactionID)

                # Remove the transaction from the current list
                self.transactions.remove(transaction)

    def createTransactionLog(self, transaction):
        self.logger.info('creating log file for transaction ' + transaction.transactionID)
        with open(self.currentTransactionsDirectory + transaction.transactionID + '.log', 'w') as transFile:
            transFile.write('TransactionID: ' + transaction.transactionID + '\n')
            transFile.write('Timestamp: ' + str(transaction.transactionCreationTime) + '\n')
            transFile.write('UTC Time: ' + time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(transaction.transactionCreationTime)) + '\n')
            transFile.write('EST Time: ' + time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(transaction.transactionCreationTime)) + '\n')
            transFile.write('dogeSeller: ' + transaction.dogeSeller + '\n')
            transFile.write('dogeBuyer: ' + transaction.dogeBuyer + '\n')
            transFile.write('dogeAmount: ' + transaction.dogeAmount + '\n')
            transFile.write('payment: ' + transaction.payment + '\n')
            transFile.write('proveTransactionID: transactionID = hashlib.sha256("' + transaction.message.body.replace('\n', '\\n') + '" + str(' + str(transaction.transactionCreationTime) + ')).hexdigest()' + '\n')

    def moveTransactionToDeclinedFolder(self, transactionID):
        self.logger.info('moving log file to declined folder for transaction ' + transactionID)
        shutil.move(self.currentTransactionsDirectory + transactionID + '.log', self.declinedTransactionsDirectory)

    def moveTransactionToCompletedFolder(self, transactionID):
        self.logger.info('moving log file to completed folder for transaction ' + transactionID)
        shutil.move(self.currentTransactionsDirectory + transactionID + '.log', self.completedTransactionsDirectory)

    def removeTransactionFile(self, transactionID):
        self.logger.info('deleting log file for transaction ' + transactionID)
        os.remove(self.currentTransactionsDirectory + transactionID + '.log')

    def getRegistrationStatusMessage(self, username):
        if(username in self.passphraseDict):
            # Return the message with the passphrase
            return self.getRegisteredMessage(username)
            pass
        else:
            return self.getUnregisteredMessage()

    def getUnregisteredMessage(self):
        registerLink = self._getRegisterLink()
        return '***Your account is currently unregistered. Fix this: [[REGISTER]](' + registerLink + ')***\n\n' + HORIZONTAL_LINE + '\n\n'

    def _getRegisterLink(self):
        return 'http://www.reddit.com/message/compose/?to=dogeescrowbot&subject=%2Bregister&message=Enter%20a%20secret%20passphrase%20below.%20This%20passphrase%20will%20be%20shown%20to%20you%20in%20the%20future%20whenever%20the%20bot%20responds.%20This%20proves%20you%20are%20talking%20to%20the%20real%20bot%20and%20not%20an%20impostor.%0A%0APassphrase:%20[correct%20horse%20battery%20staple]'

    def getRegisteredMessage(self, username):
        return 'Your secret passphrase is [**' + self.passphraseDict[username] + '**] [[CHANGE PASS]](' + self._getRegisterLink() + ')\n\n' + HORIZONTAL_LINE + '\n\n'

    def getTransaction(self, message):
        # See if the transactionID in the body matches a current transaction
        for transaction in self.transactions:
            if(transaction.transactionID in message.body):
                return transaction
        # If it doesn't, return False
        return None

    def replyToInvalidTransactionID(self, message):
        response = 'Sorry, the transactionID you sent doesn\'t match a current \
        transaction. Please re-send with the correct transactionID.'
        self.replyToMessage(message, response)

    def sendMessage(self, username, subject, body):
        # Prepend registration message
        body = self.getRegistrationStatusMessage(username) + body
        # Log and send
        self.logger.debug('Sending message to /u/' + username + '\nsubject: ' + subject + '\nbody: ' + body.replace('\n\n', '\n'))
        self.rConn.send_message(username, subject, body)

    def replyToMessage(self, message, response):
        # Prepend registration message
        response = self.getRegistrationStatusMessage(message.author.name) + response
        # Log and send
        self.logger.debug('Sending response to /u/' + message.author.name + ': \n' + response.replace('\n\n', '\n'))
        message.reply(response)

    def logIncomingTransactionMessage(self, transaction, message):
        self.logger.info('logging transaction details for transaction ' + transaction.transactionID)
        with open(self.currentTransactionsDirectory + transaction.transactionID + '.log', 'a') as transFile:
            try:
                transFile.write('\n')
                transFile.write('Timestamp: ' + str(message.created_utc) + '\n')
                transFile.write('UTC Time: ' + time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(message.created_utc)) + '\n')
                transFile.write('EST Time: ' + time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(message.created_utc)) + '\n')
                transFile.write('From: ' + message.author.name + '\n')
                transFile.write('Subject: ' + message.subject + '\n')
                transFile.write('Body: ' + message.body + '\n')
                transFile.write('--------------------------\n')
            except Exception, e:
                self.logger.warning('unable to log message: %s | error: %s ', body, e)
                raise

    def logOutgoingTransactionMessage(self, transaction, toUser, subject, body):
        self.logger.info('logging transaction details for transaction ' + transaction.transactionID)
        currentTime = time.time()
        with open(self.currentTransactionsDirectory + transaction.transactionID + '.log', 'a') as transFile:
            try:
                transFile.write('\n')
                transFile.write('Approximate Timestamp: ' + str(currentTime) + '\n')
                transFile.write('Approximate UTC Time: ' + time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(currentTime)) + '\n')
                transFile.write('Approximate EST Time: ' + time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(currentTime)) + '\n')
                transFile.write('To: ' + toUser + '\n')
                transFile.write('Subject: ' + subject + '\n')
                transFile.write('Body: ' + body + '\n')
                transFile.write('--------------------------\n')
            except Exception, e:
                self.logger.warning('unable to log message: %s | error: %s ', body, e)
                raise


    def _logHandleRequest(self, requestType):
        self.logger.info('handling new "' + requestType + '" request')

class ParseError(Exception):
    pass

if __name__ == '__main__':
    LOG.info('=========================================')
    LOG.info('starting EscrowBot().start()')
    sys.exit(EscrowBot().start())






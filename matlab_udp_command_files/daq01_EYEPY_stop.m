function [success,msg] = daq01_EYEPY_start(expID)

% eyepy server
address = '127.0.0.1';
port = 12345;

if ~exist('expID')
    expID = '2016-10-14_09_CFAP049';
end

try
    % Create UDP object
    udpObj = udpport("datagram", "IPV4");
    % Send message
    write(udpObj, uint8(['STOP','*', expID]),'uint8', address, port);
    % Clean up
    clear udpObj;
    success = true;
    msg = 'All good';
catch
    try
        % Close connection
        clear udpObj;
    catch
    end
    success = false;
    msg = 'Unknown error';
end

end